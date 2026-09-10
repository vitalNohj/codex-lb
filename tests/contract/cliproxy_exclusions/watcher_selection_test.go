// Opt-in contract test material for CLIProxyAPI commit
// 856ddd8df746a38a6033dbbf6c140974bf5aea0f. Run only through run.sh.
package cliproxy

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/router-for-me/CLIProxyAPI/v7/internal/registry"
	coreauth "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/auth"
	cliproxyexecutor "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/executor"
	"github.com/router-for-me/CLIProxyAPI/v7/sdk/config"
)

const watcherContractModel = "claude-opus-4-6"

type watcherContractExecutor struct {
	mu    sync.Mutex
	calls []string
}

func (e *watcherContractExecutor) Identifier() string { return "claude" }

func (e *watcherContractExecutor) Execute(_ context.Context, auth *coreauth.Auth, _ cliproxyexecutor.Request, _ cliproxyexecutor.Options) (cliproxyexecutor.Response, error) {
	e.mu.Lock()
	e.calls = append(e.calls, auth.ID)
	e.mu.Unlock()
	return cliproxyexecutor.Response{Payload: []byte(auth.ID)}, nil
}

func (e *watcherContractExecutor) ExecuteStream(_ context.Context, _ *coreauth.Auth, _ cliproxyexecutor.Request, _ cliproxyexecutor.Options) (*cliproxyexecutor.StreamResult, error) {
	return nil, &coreauth.Error{HTTPStatus: http.StatusInternalServerError, Message: "streaming is outside this contract"}
}

func (e *watcherContractExecutor) Refresh(_ context.Context, auth *coreauth.Auth) (*coreauth.Auth, error) {
	return auth, nil
}

func (e *watcherContractExecutor) CountTokens(_ context.Context, auth *coreauth.Auth, _ cliproxyexecutor.Request, _ cliproxyexecutor.Options) (cliproxyexecutor.Response, error) {
	return cliproxyexecutor.Response{Payload: []byte(auth.ID)}, nil
}

func (e *watcherContractExecutor) HttpRequest(context.Context, *coreauth.Auth, *http.Request) (*http.Response, error) {
	return nil, nil
}

func (e *watcherContractExecutor) callCount(id string) int {
	e.mu.Lock()
	defer e.mu.Unlock()
	count := 0
	for _, call := range e.calls {
		if call == id {
			count++
		}
	}
	return count
}

func writeWatcherContractAuth(t *testing.T, dir, name string, excluded []string) string {
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
	blob, errMarshal := json.Marshal(payload)
	if errMarshal != nil {
		t.Fatalf("marshal %s auth: %v", name, errMarshal)
	}
	path := filepath.Join(dir, name+".json")
	if errWrite := os.WriteFile(path, blob, 0o600); errWrite != nil {
		t.Fatalf("save %s auth: %v", name, errWrite)
	}
	return path
}

func waitForWatcherContract(t *testing.T, label string, condition func() bool) {
	t.Helper()
	if condition() {
		return
	}
	timer := time.NewTimer(5 * time.Second)
	defer timer.Stop()
	ticker := time.NewTicker(10 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			if condition() {
				return
			}
		case <-timer.C:
			t.Fatalf("timed out waiting for %s", label)
		}
	}
}

func watcherContractState(manager *coreauth.Manager, authID, excluded string, supports bool) bool {
	auth, ok := manager.GetByID(authID)
	if !ok || auth == nil {
		return false
	}
	gotExcluded := ""
	if auth.Attributes != nil {
		gotExcluded = auth.Attributes["excluded_models"]
	}
	if gotExcluded != excluded {
		return false
	}
	return registry.GetGlobalRegistry().ClientSupportsModel(authID, watcherContractModel) == supports
}

func executeWatcherContract(t *testing.T, service *Service, manager *coreauth.Manager, executor *watcherContractExecutor, count int) map[string]int {
	t.Helper()
	service.executorRegistrationMu.Lock()
	defer service.executorRegistrationMu.Unlock()
	manager.RegisterExecutor(executor)
	beforeAlpha := executor.callCount("alpha.json")
	beforeBravo := executor.callCount("bravo.json")
	for i := 0; i < count; i++ {
		response, errExecute := manager.Execute(
			context.Background(),
			[]string{"claude"},
			cliproxyexecutor.Request{Model: watcherContractModel},
			cliproxyexecutor.Options{},
		)
		if errExecute != nil {
			t.Fatalf("request %d: %v", i, errExecute)
		}
		if len(response.Payload) == 0 {
			t.Fatalf("request %d returned an empty provider payload", i)
		}
	}
	return map[string]int{
		"alpha.json": executor.callCount("alpha.json") - beforeAlpha,
		"bravo.json": executor.callCount("bravo.json") - beforeBravo,
	}
}

func TestExclusionWatcher_SavedAddAndClearReachSelection(t *testing.T) {
	authDir := t.TempDir()
	configPath := filepath.Join(t.TempDir(), "config.yaml")
	if errWrite := os.WriteFile(configPath, []byte("{}\n"), 0o600); errWrite != nil {
		t.Fatalf("write watcher config: %v", errWrite)
	}

	alphaPath := writeWatcherContractAuth(t, authDir, "alpha", nil)
	writeWatcherContractAuth(t, authDir, "bravo", nil)

	manager := coreauth.NewManager(nil, nil, nil)
	executor := &watcherContractExecutor{}
	manager.RegisterExecutor(executor)

	cfg := &config.Config{AuthDir: authDir}
	service := &Service{cfg: cfg, configPath: configPath, coreManager: manager}
	ctx, cancel := context.WithCancel(context.Background())
	service.ensureAuthUpdateQueue(ctx)

	watcherWrapper, errWatcher := defaultWatcherFactory(configPath, authDir, func(*config.Config) {})
	if errWatcher != nil {
		cancel()
		t.Fatalf("construct watcher: %v", errWatcher)
	}
	service.watcher = watcherWrapper
	watcherWrapper.SetConfig(cfg)
	watcherWrapper.SetAuthUpdateQueue(service.authUpdates)
	if errStart := watcherWrapper.Start(ctx); errStart != nil {
		cancel()
		_ = watcherWrapper.Stop()
		t.Fatalf("start watcher: %v", errStart)
	}
	t.Cleanup(func() {
		cancel()
		if service.authQueueStop != nil {
			service.authQueueStop()
		}
		_ = watcherWrapper.Stop()
		registry.GetGlobalRegistry().UnregisterClient("alpha.json")
		registry.GetGlobalRegistry().UnregisterClient("bravo.json")
	})

	waitForWatcherContract(t, "initial alpha registration", func() bool {
		return watcherContractState(manager, "alpha.json", "", true)
	})
	waitForWatcherContract(t, "initial bravo registration", func() bool {
		return watcherContractState(manager, "bravo.json", "", true)
	})
	served := executeWatcherContract(t, service, manager, executor, 4)
	if served["alpha.json"] == 0 || served["bravo.json"] == 0 {
		t.Fatalf("initial phase served %v, want both accounts", served)
	}

	writeWatcherContractAuth(t, authDir, "alpha", []string{watcherContractModel})
	waitForWatcherContract(t, "saved exclusion to reach selection", func() bool {
		return watcherContractState(manager, "alpha.json", watcherContractModel, false) &&
			watcherContractState(manager, "bravo.json", "", true)
	})
	served = executeWatcherContract(t, service, manager, executor, 4)
	if served["alpha.json"] != 0 || served["bravo.json"] != 4 {
		t.Fatalf("excluded phase served %v, want only bravo", served)
	}

	writeWatcherContractAuth(t, authDir, "alpha", []string{})
	waitForWatcherContract(t, "cleared exclusion to reach selection", func() bool {
		return watcherContractState(manager, "alpha.json", "", true) &&
			watcherContractState(manager, "bravo.json", "", true)
	})
	served = executeWatcherContract(t, service, manager, executor, 4)
	if served["alpha.json"] == 0 || served["bravo.json"] == 0 {
		t.Fatalf("cleared phase served %v, want both accounts", served)
	}

	if _, ok := manager.GetByID(filepath.Base(alphaPath)); !ok {
		t.Fatal("alpha disappeared from the original manager")
	}
}
