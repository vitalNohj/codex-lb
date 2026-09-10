// Opt-in Go backing for the cross-language HTTP contract. It is compiled into
// the pinned CLIProxyAPI management package with go test -overlay and does not
// modify that checkout. Overlay target:
//
//	internal/api/handlers/management/codex_lb_http_fixture_test.go
package management

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/config"
	fileauth "github.com/router-for-me/CLIProxyAPI/v7/sdk/auth"
	coreauth "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/auth"
)

const fixtureManagementKey = "synthetic-management-key"

func TestCodexLBManagementHTTPFixture(t *testing.T) {
	if os.Getenv("CODEX_LB_HTTP_FIXTURE") != "1" {
		t.Skip("fixture process only")
	}
	addr := os.Getenv("CODEX_LB_HTTP_FIXTURE_ADDR")
	authDir := os.Getenv("CODEX_LB_HTTP_FIXTURE_AUTH_DIR")
	readyPath := os.Getenv("CODEX_LB_HTTP_FIXTURE_READY")
	stopPath := os.Getenv("CODEX_LB_HTTP_FIXTURE_STOP")
	for key, value := range map[string]string{
		"CODEX_LB_HTTP_FIXTURE_ADDR":     addr,
		"CODEX_LB_HTTP_FIXTURE_AUTH_DIR": authDir,
		"CODEX_LB_HTTP_FIXTURE_READY":    readyPath,
		"CODEX_LB_HTTP_FIXTURE_STOP":     stopPath,
	} {
		if value == "" {
			t.Fatalf("%s is required", key)
		}
	}

	store := fileauth.NewFileTokenStore()
	store.SetBaseDir(authDir)
	fileauth.RegisterTokenStore(store)
	manager := coreauth.NewManager(store, nil, nil)
	for _, name := range []string{"alpha.json", "bravo.json"} {
		path := filepath.Join(authDir, name)
		data, errRead := os.ReadFile(path)
		if errRead != nil {
			t.Fatalf("read %s: %v", name, errRead)
		}
		metadata := make(map[string]any)
		if errJSON := json.Unmarshal(data, &metadata); errJSON != nil {
			t.Fatalf("parse %s: %v", name, errJSON)
		}
		auth := &coreauth.Auth{
			ID:       name,
			FileName: name,
			Provider: "claude",
			Label:    fmt.Sprint(metadata["email"]),
			Attributes: map[string]string{
				coreauth.AttributePath:          path,
				coreauth.AttributeSource:        path,
				coreauth.AttributeSourceBackend: coreauth.AuthSourceFile,
			},
			Metadata: metadata,
		}
		if _, errRegister := manager.Register(context.Background(), auth); errRegister != nil {
			t.Fatalf("register %s: %v", name, errRegister)
		}
	}

	cfg := &config.Config{AuthDir: authDir}
	cfg.Routing.Strategy = "round-robin"
	t.Setenv("MANAGEMENT_PASSWORD", fixtureManagementKey)
	handler := NewHandlerWithoutConfigFilePath(cfg, manager)

	gin.SetMode(gin.TestMode)
	router := gin.New()
	management := router.Group("/v0/management", handler.Middleware())
	management.GET("/routing/strategy", handler.GetRoutingStrategy)
	management.GET("/auth-files", handler.ListAuthFiles)
	management.PATCH("/auth-files/fields", handler.PatchAuthFileFields)

	listener, errListen := net.Listen("tcp4", addr)
	if errListen != nil {
		t.Fatalf("listen on bound fixture address: %v", errListen)
	}
	server := &http.Server{Handler: router, ReadHeaderTimeout: 2 * time.Second}
	serveDone := make(chan error, 1)
	go func() { serveDone <- server.Serve(listener) }()
	if errReady := os.WriteFile(readyPath, []byte(listener.Addr().String()+"\n"), 0o600); errReady != nil {
		_ = listener.Close()
		t.Fatalf("write ready file: %v", errReady)
	}

	deadline := time.NewTimer(70 * time.Second)
	defer deadline.Stop()
	ticker := time.NewTicker(20 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case errServe := <-serveDone:
			if errServe != nil && errServe != http.ErrServerClosed {
				t.Fatalf("fixture server: %v", errServe)
			}
			return
		case <-ticker.C:
			if _, errStop := os.Stat(stopPath); errStop == nil {
				ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
				defer cancel()
				if errShutdown := server.Shutdown(ctx); errShutdown != nil {
					t.Fatalf("fixture shutdown: %v", errShutdown)
				}
				errServe := <-serveDone
				if errServe != nil && errServe != http.ErrServerClosed {
					t.Fatalf("fixture server stop: %v", errServe)
				}
				return
			}
		case <-deadline.C:
			_ = server.Close()
			t.Fatal("fixture stop deadline exceeded")
		}
	}
}
