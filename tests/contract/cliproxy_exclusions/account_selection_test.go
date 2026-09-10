// Opt-in contract test material for CLIProxyAPI commit
// 856ddd8df746a38a6033dbbf6c140974bf5aea0f. Run only through run.sh.
package cliproxy

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/router-for-me/CLIProxyAPI/v7/internal/registry"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/watcher/synthesizer"
	coreauth "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/auth"
	cliproxyexecutor "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/executor"
	"github.com/router-for-me/CLIProxyAPI/v7/sdk/config"
)

const (
	exclContractExact    = "claude-opus-4-6"
	exclContractSibling  = "claude-opus-4-7"
	exclContractOutside  = "claude-opus-5"
	exclContractWildcard = "claude-opus-4-*"
)

type recordingExecutor struct {
	id string

	calls     []string
	failWith  map[string]error
	failEvery bool
}

func (e *recordingExecutor) Identifier() string { return e.id }

func (e *recordingExecutor) Execute(_ context.Context, auth *coreauth.Auth, _ cliproxyexecutor.Request, _ cliproxyexecutor.Options) (cliproxyexecutor.Response, error) {
	e.calls = append(e.calls, auth.ID)
	if e.failEvery {
		return cliproxyexecutor.Response{}, &coreauth.Error{HTTPStatus: http.StatusInternalServerError, Message: "synthetic upstream failure"}
	}
	if err := e.failWith[auth.ID]; err != nil {
		return cliproxyexecutor.Response{}, err
	}
	return cliproxyexecutor.Response{Payload: []byte(auth.ID)}, nil
}

func (e *recordingExecutor) ExecuteStream(_ context.Context, auth *coreauth.Auth, _ cliproxyexecutor.Request, _ cliproxyexecutor.Options) (*cliproxyexecutor.StreamResult, error) {
	e.calls = append(e.calls, auth.ID)
	return nil, &coreauth.Error{HTTPStatus: http.StatusInternalServerError, Message: "synthetic upstream failure"}
}

func (e *recordingExecutor) Refresh(_ context.Context, auth *coreauth.Auth) (*coreauth.Auth, error) {
	return auth, nil
}

func (e *recordingExecutor) CountTokens(_ context.Context, auth *coreauth.Auth, _ cliproxyexecutor.Request, _ cliproxyexecutor.Options) (cliproxyexecutor.Response, error) {
	return cliproxyexecutor.Response{Payload: []byte(auth.ID)}, nil
}

func (e *recordingExecutor) HttpRequest(context.Context, *coreauth.Auth, *http.Request) (*http.Response, error) {
	return nil, nil
}

func (e *recordingExecutor) took(id string) bool {
	for _, call := range e.calls {
		if call == id {
			return true
		}
	}
	return false
}

func writeSyntheticAuthFile(t *testing.T, dir, name string, excluded []string) string {
	t.Helper()
	payload := map[string]any{
		"type":          "claude",
		"email":         name + "@synthetic.invalid",
		"access_token":  "synthetic-token-" + name,
		"refresh_token": "synthetic-refresh-" + name,
		"expired":       "2099-01-01T00:00:00Z",
	}
	if excluded != nil {
		payload["excluded_models"] = excluded
	}
	blob, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal synthetic auth file: %v", err)
	}
	path := filepath.Join(dir, name+".json")
	if errWrite := os.WriteFile(path, blob, 0o600); errWrite != nil {
		t.Fatalf("write synthetic auth file: %v", errWrite)
	}
	return path
}

func writeSyntheticAuthFileWithAliases(t *testing.T, dir, name string, excluded []string, aliases []map[string]any) string {
	t.Helper()
	payload := map[string]any{
		"type":          "claude",
		"email":         name + "@synthetic.invalid",
		"access_token":  "synthetic-token-" + name,
		"refresh_token": "synthetic-refresh-" + name,
		"expired":       "2099-01-01T00:00:00Z",
	}
	if excluded != nil {
		payload["excluded_models"] = excluded
	}
	if aliases != nil {
		payload["model_aliases"] = aliases
	}
	blob, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal synthetic auth file with aliases: %v", err)
	}
	path := filepath.Join(dir, name+".json")
	if errWrite := os.WriteFile(path, blob, 0o600); errWrite != nil {
		t.Fatalf("write synthetic auth file with aliases: %v", errWrite)
	}
	return path
}

func exclContractRegisteredIDs(auth *coreauth.Auth) map[string]struct{} {
	out := make(map[string]struct{})
	for _, model := range registry.GetGlobalRegistry().GetModelsForClient(auth.ID) {
		if model == nil {
			continue
		}
		out[model.ID] = struct{}{}
	}
	return out
}

func parseAndRegister(t *testing.T, svc *Service, authDir, path string) *coreauth.Auth {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read synthetic auth file: %v", err)
	}
	auths, errSynth := synthesizer.SynthesizeAuthFile(&synthesizer.SynthesisContext{
		Config:      &config.Config{},
		AuthDir:     authDir,
		Now:         time.Now(),
		IDGenerator: synthesizer.NewStableIDGenerator(),
	}, path, data)
	if errSynth != nil {
		t.Fatalf("synthesize auth file: %v", errSynth)
	}
	if len(auths) != 1 {
		t.Fatalf("synthesize returned %d auths, want 1", len(auths))
	}
	auth := auths[0]
	registry.GetGlobalRegistry().UnregisterClient(auth.ID)
	svc.registerModelsForAuth(context.Background(), auth)
	t.Cleanup(func() { registry.GetGlobalRegistry().UnregisterClient(auth.ID) })
	return auth
}

func eligibleFor(model string, auths ...*coreauth.Auth) []string {
	reg := registry.GetGlobalRegistry()
	var out []string
	for _, auth := range auths {
		if reg.ClientSupportsModel(auth.ID, model) {
			out = append(out, auth.ID)
		}
	}
	return out
}

func newContractService() *Service {
	return &Service{cfg: &config.Config{}}
}

func newContractManager(t *testing.T, exec *recordingExecutor, auths ...*coreauth.Auth) *coreauth.Manager {
	t.Helper()
	m := coreauth.NewManager(nil, nil, nil)
	m.RegisterExecutor(exec)
	for _, auth := range auths {
		if _, err := m.Register(context.Background(), auth); err != nil {
			t.Fatalf("register auth %s: %v", auth.ID, err)
		}
	}
	return m
}

func TestExclusionContract_ExactIDSkipsOnlyThatWireID(t *testing.T) {
	dir := t.TempDir()
	svc := newContractService()

	alphaPath := writeSyntheticAuthFile(t, dir, "alpha", []string{exclContractExact})
	bravoPath := writeSyntheticAuthFile(t, dir, "bravo", nil)
	alpha := parseAndRegister(t, svc, dir, alphaPath)
	bravo := parseAndRegister(t, svc, dir, bravoPath)

	if got := eligibleFor(exclContractExact, alpha, bravo); len(got) != 1 || got[0] != bravo.ID {
		t.Fatalf("eligible for %s = %v, want only %s", exclContractExact, got, bravo.ID)
	}
	if got := eligibleFor(exclContractSibling, alpha, bravo); len(got) != 2 {
		t.Fatalf("eligible for %s = %v, want both accounts", exclContractSibling, got)
	}
	if got := eligibleFor(exclContractOutside, alpha, bravo); len(got) != 2 {
		t.Fatalf("eligible for %s = %v, want both accounts", exclContractOutside, got)
	}
	if _, ok := bravo.Attributes["excluded_models"]; ok {
		t.Fatal("bravo must keep its own empty exclusion list")
	}
}

func TestExclusionContract_ExplicitWildcardSkipsEveryMatch(t *testing.T) {
	dir := t.TempDir()
	svc := newContractService()

	alpha := parseAndRegister(t, svc, dir, writeSyntheticAuthFile(t, dir, "alpha", []string{exclContractWildcard}))
	bravo := parseAndRegister(t, svc, dir, writeSyntheticAuthFile(t, dir, "bravo", nil))

	for _, model := range []string{exclContractExact, exclContractSibling} {
		if got := eligibleFor(model, alpha, bravo); len(got) != 1 || got[0] != bravo.ID {
			t.Fatalf("eligible for %s = %v, want only %s", model, got, bravo.ID)
		}
	}
	if got := eligibleFor(exclContractOutside, alpha, bravo); len(got) != 2 {
		t.Fatalf("eligible for %s = %v, want both accounts (outside the pattern)", exclContractOutside, got)
	}
}

func TestExclusionContract_ExcludedAccountReceivesNoCallOnSelectionOrRetry(t *testing.T) {
	dir := t.TempDir()
	svc := newContractService()

	alpha := parseAndRegister(t, svc, dir, writeSyntheticAuthFile(t, dir, "alpha", []string{exclContractExact}))
	bravo := parseAndRegister(t, svc, dir, writeSyntheticAuthFile(t, dir, "bravo", nil))

	excludedExec := &recordingExecutor{id: "claude", failEvery: true}
	m := newContractManager(t, excludedExec, alpha, bravo)
	if _, err := m.Execute(context.Background(), []string{"claude"},
		cliproxyexecutor.Request{Model: exclContractExact}, cliproxyexecutor.Options{}); err == nil {
		t.Fatal("expected the forced-failure request to end in error")
	}
	if excludedExec.took(alpha.ID) {
		t.Fatalf("excluded account was called: %v", excludedExec.calls)
	}
	if !excludedExec.took(bravo.ID) {
		t.Fatalf("eligible account was never called: %v", excludedExec.calls)
	}

	controlExec := &recordingExecutor{id: "claude", failEvery: true}
	mc := newContractManager(t, controlExec, alpha, bravo)
	if _, err := mc.Execute(context.Background(), []string{"claude"},
		cliproxyexecutor.Request{Model: exclContractSibling}, cliproxyexecutor.Options{}); err == nil {
		t.Fatal("expected the forced-failure control request to end in error")
	}
	if !controlExec.took(alpha.ID) || !controlExec.took(bravo.ID) {
		t.Fatalf("control retry path did not span both accounts: %v", controlExec.calls)
	}
}

func TestExclusionContract_AnotherEligibleAccountServes(t *testing.T) {
	dir := t.TempDir()
	svc := newContractService()

	alpha := parseAndRegister(t, svc, dir, writeSyntheticAuthFile(t, dir, "alpha", []string{exclContractExact}))
	bravo := parseAndRegister(t, svc, dir, writeSyntheticAuthFile(t, dir, "bravo", nil))

	exec := &recordingExecutor{id: "claude"}
	m := newContractManager(t, exec, alpha, bravo)
	resp, err := m.Execute(context.Background(), []string{"claude"},
		cliproxyexecutor.Request{Model: exclContractExact}, cliproxyexecutor.Options{})
	if err != nil {
		t.Fatalf("execute = %v, want success on the eligible account", err)
	}
	if string(resp.Payload) != bravo.ID {
		t.Fatalf("served by %q, want %q", string(resp.Payload), bravo.ID)
	}
	if exec.took(alpha.ID) {
		t.Fatalf("excluded account was called: %v", exec.calls)
	}
}

func TestExclusionContract_NoEligibleAccountPreservesExhaustion(t *testing.T) {
	dir := t.TempDir()
	svc := newContractService()

	alpha := parseAndRegister(t, svc, dir, writeSyntheticAuthFile(t, dir, "alpha", []string{exclContractExact}))
	bravo := parseAndRegister(t, svc, dir, writeSyntheticAuthFile(t, dir, "bravo", []string{exclContractExact}))

	if got := eligibleFor(exclContractExact, alpha, bravo); len(got) != 0 {
		t.Fatalf("eligible for %s = %v, want none", exclContractExact, got)
	}

	exec := &recordingExecutor{id: "claude"}
	m := newContractManager(t, exec, alpha, bravo)
	_, err := m.Execute(context.Background(), []string{"claude"},
		cliproxyexecutor.Request{Model: exclContractExact}, cliproxyexecutor.Options{})
	if err == nil {
		t.Fatal("expected the existing exhaustion error, got success")
	}
	var authErr *coreauth.Error
	if !errors.As(err, &authErr) || authErr.Code != "auth_not_found" {
		t.Fatalf("exhaustion error = %v, want code auth_not_found", err)
	}
	if len(exec.calls) != 0 {
		t.Fatalf("no account should have been called, got %v", exec.calls)
	}

	if got := eligibleFor(exclContractSibling, alpha, bravo); len(got) != 2 {
		t.Fatalf("eligible for %s = %v, want both accounts", exclContractSibling, got)
	}
}

func exclContractSyncAuth(t *testing.T, svc *Service, m *coreauth.Manager, dir, name string, excluded []string) *coreauth.Auth {
	t.Helper()
	path := writeSyntheticAuthFile(t, dir, name, excluded)
	auth := parseAndRegister(t, svc, dir, path)

	ctx := context.Background()
	if _, known := m.GetByID(auth.ID); known {
		updated, errUpdate := m.Update(ctx, auth)
		if errUpdate != nil {
			t.Fatalf("update auth %s: %v", auth.ID, errUpdate)
		}
		if updated == nil {
			t.Fatalf("update auth %s returned no auth", auth.ID)
		}
	} else if _, errRegister := m.Register(ctx, auth); errRegister != nil {
		t.Fatalf("register auth %s: %v", auth.ID, errRegister)
	}
	m.RefreshSchedulerEntry(auth.ID)
	return auth
}

func exclContractDrain(t *testing.T, m *coreauth.Manager, exec *recordingExecutor, model string, n int) map[string]int {
	t.Helper()
	start := len(exec.calls)
	for i := 0; i < n; i++ {
		resp, err := m.Execute(context.Background(), []string{"claude"},
			cliproxyexecutor.Request{Model: model}, cliproxyexecutor.Options{})
		if err != nil {
			t.Fatalf("request %d for %s: %v, want success", i, model, err)
		}
		if len(exec.calls) == 0 || string(resp.Payload) != exec.calls[len(exec.calls)-1] {
			t.Fatalf("request %d: payload %q does not match the account the executor was handed", i, string(resp.Payload))
		}
	}
	served := make(map[string]int)
	for _, id := range exec.calls[start:] {
		served[id]++
	}
	return served
}

func TestExclusionContract_ToggleChangesEligibilityWithoutRestart(t *testing.T) {
	dir := t.TempDir()
	svc := newContractService()

	exec := &recordingExecutor{id: "claude"}
	m := coreauth.NewManager(nil, nil, nil)
	m.RegisterExecutor(exec)

	alpha := exclContractSyncAuth(t, svc, m, dir, "alpha", nil)
	bravo := exclContractSyncAuth(t, svc, m, dir, "bravo", nil)
	if got := eligibleFor(exclContractExact, alpha, bravo); len(got) != 2 {
		t.Fatalf("permitted phase: eligible = %v, want both accounts", got)
	}
	served := exclContractDrain(t, m, exec, exclContractExact, 4)
	if served[alpha.ID] == 0 || served[bravo.ID] == 0 {
		t.Fatalf("permitted phase: served = %v, want both accounts called", served)
	}

	alpha = exclContractSyncAuth(t, svc, m, dir, "alpha", []string{exclContractExact})
	if got := eligibleFor(exclContractExact, alpha, bravo); len(got) != 1 || got[0] != bravo.ID {
		t.Fatalf("excluded phase: eligible = %v, want only %s", got, bravo.ID)
	}
	served = exclContractDrain(t, m, exec, exclContractExact, 4)
	if served[alpha.ID] != 0 {
		t.Fatalf("excluded phase: excluded account was called %d times: %v", served[alpha.ID], served)
	}
	if served[bravo.ID] != 4 {
		t.Fatalf("excluded phase: served = %v, want all 4 requests on %s", served, bravo.ID)
	}

	alpha = exclContractSyncAuth(t, svc, m, dir, "alpha", []string{})
	if got := eligibleFor(exclContractExact, alpha, bravo); len(got) != 2 {
		t.Fatalf("cleared phase: eligible = %v, want both accounts", got)
	}
	served = exclContractDrain(t, m, exec, exclContractExact, 4)
	if served[alpha.ID] == 0 {
		t.Fatalf("cleared phase: previously excluded account was still never called: %v", served)
	}
	if served[bravo.ID] == 0 {
		t.Fatalf("cleared phase: served = %v, want the unrelated account still usable", served)
	}
}

const exclContractAlias = "synthetic-house-model"

func TestExclusionContract_AliasDoesNotReviveExcludedWireID(t *testing.T) {
	dir := t.TempDir()
	svc := newContractService()

	aliasEntries := []map[string]any{
		{"name": exclContractExact, "alias": exclContractAlias},
	}

	alpha := parseAndRegister(t, svc, dir,
		writeSyntheticAuthFileWithAliases(t, dir, "alpha", []string{exclContractExact}, aliasEntries))
	bravo := parseAndRegister(t, svc, dir,
		writeSyntheticAuthFileWithAliases(t, dir, "bravo", nil, aliasEntries))

	alphaIDs := exclContractRegisteredIDs(alpha)
	bravoIDs := exclContractRegisteredIDs(bravo)

	if _, ok := bravoIDs[exclContractAlias]; !ok {
		t.Fatalf("control: alias %s absent on the permitted account; alias mechanism did not apply", exclContractAlias)
	}
	if _, ok := bravoIDs[exclContractExact]; ok {
		t.Fatalf("control: permitted account still carries the replaced wire id %s", exclContractExact)
	}
	if _, ok := alphaIDs[exclContractExact]; ok {
		t.Fatalf("excluded account still carries the excluded wire id %s", exclContractExact)
	}
	if _, ok := alphaIDs[exclContractAlias]; ok {
		t.Fatalf("excluded wire id came back through its alias %s on the excluded account", exclContractAlias)
	}
	for _, auth := range []*coreauth.Auth{alpha, bravo} {
		if _, ok := exclContractRegisteredIDs(auth)[exclContractSibling]; !ok {
			t.Fatalf("permitted model %s missing on %s", exclContractSibling, auth.ID)
		}
	}

	exec := &recordingExecutor{id: "claude"}
	m := newContractManager(t, exec, alpha, bravo)
	resp, err := m.Execute(context.Background(), []string{"claude"},
		cliproxyexecutor.Request{Model: exclContractAlias}, cliproxyexecutor.Options{})
	if err != nil {
		t.Fatalf("alias request = %v, want success on the permitted account %s", err, bravo.ID)
	}
	if string(resp.Payload) != bravo.ID {
		t.Fatalf("alias request served by %q, want the permitted account %q", string(resp.Payload), bravo.ID)
	}
	if exec.took(alpha.ID) {
		t.Fatalf("excluded account was called for the alias: %v", exec.calls)
	}
}
