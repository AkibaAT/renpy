# Oka'Py Cloud Saves - Implementation Plan

**Status:** Planned
**Priority:** Future
**Created:** 2026-01-02

## Overview

Replace Ren'Py's temporary "sync" feature (1-hour expiration, manual code sharing) with persistent cloud saves featuring OAuth authentication and automatic synchronization.

## Current System Limitations

| Aspect | Current Ren'Py Sync |
|--------|---------------------|
| Storage duration | 1 hour expiration |
| Authentication | None - random 11-char code |
| Sync trigger | Manual upload/download |
| Conflict handling | Overwrites without warning |
| Save history | None - single snapshot |
| Account system | None |
| Server | sync.renpy.org |

## Proposed Oka'Py Cloud Saves

### Design Decisions

- **Authentication:** OAuth providers (Discord, GitHub, Google) - no password management
- **Storage:** Self-hosted server (cloud.okapy.li)
- **Sync behavior:** Both automatic background and manual options (user preference)

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Oka'Py Launcher / Game                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ OAuth Flow  │  │ Sync Engine │  │ Conflict Resolution UI  │  │
│  │ (browser)   │  │ (background)│  │ (screens)               │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    cloud.okapy.li                               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ /auth/discord, /auth/github, /auth/google                │   │
│  │ /auth/callback/{provider}                                │   │
│  │ /api/me                           (user profile)         │   │
│  │ /api/saves/{game}                 (list saves)           │   │
│  │ /api/saves/{game}/{slot}          (CRUD save)            │   │
│  │ /api/saves/{game}/sync            (sync metadata)        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                  │
│  ┌───────────────┐  ┌────────┴───────┐  ┌──────────────────┐   │
│  │ PostgreSQL    │  │ Object Storage │  │ Redis (sessions) │   │
│  │ (users, meta) │  │ (save files)   │  │                  │   │
│  └───────────────┘  └────────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         ┌────────┐     ┌────────┐      ┌────────┐
         │Discord │     │GitHub  │      │Google  │
         │ OAuth  │     │ OAuth  │      │ OAuth  │
         └────────┘     └────────┘      └────────┘
```

### Feature Comparison

| Feature | Current Sync | Oka'Py Cloud |
|---------|--------------|--------------|
| Duration | 1 hour | Permanent |
| Auth | Random code | Discord/GitHub/Google |
| Sync trigger | Manual only | Auto + Manual |
| Conflict handling | Overwrite | Choose/merge UI |
| Save history | None | Versioned |
| Multi-device | Copy code manually | Automatic |
| Offline play | N/A | Full support, sync when online |

## API Specification

### Authentication Endpoints

```
GET  /auth/discord              → Redirect to Discord OAuth
GET  /auth/github               → Redirect to GitHub OAuth
GET  /auth/google               → Redirect to Google OAuth
GET  /auth/callback/{provider}  → Handle OAuth callback, return JWT
POST /auth/refresh              → Refresh JWT token
POST /auth/logout               → Invalidate session
```

### User Endpoints

```
GET  /api/me                    → Get current user profile
GET  /api/me/devices            → List linked devices
DELETE /api/me/devices/{id}     → Unlink a device
DELETE /api/me                  → Delete account and all data
```

### Save Endpoints

```
GET    /api/saves/{game_id}                → List all saves for game
GET    /api/saves/{game_id}/{slot}         → Download save
PUT    /api/saves/{game_id}/{slot}         → Upload save
DELETE /api/saves/{game_id}/{slot}         → Delete save
GET    /api/saves/{game_id}/{slot}/history → Get save version history
GET    /api/saves/{game_id}/sync           → Get sync metadata (checksums, timestamps)
POST   /api/saves/{game_id}/sync           → Batch sync (upload changes, get conflicts)
```

### Data Models

```python
# User
{
    "id": "uuid",
    "created_at": "timestamp",
    "oauth_provider": "discord|github|google",
    "oauth_id": "string",
    "username": "string",
    "avatar_url": "string",
    "storage_used_bytes": 0,
    "storage_limit_bytes": 104857600  # 100 MB default
}

# Save
{
    "id": "uuid",
    "user_id": "uuid",
    "game_id": "string",  # from config.save_directory
    "slot": "string",     # e.g., "1", "quick-1", "auto-1"
    "checksum": "sha256",
    "size_bytes": 0,
    "created_at": "timestamp",
    "updated_at": "timestamp",
    "device_id": "string",
    "version": 1
}

# SyncMetadata
{
    "game_id": "string",
    "last_sync": "timestamp",
    "saves": {
        "slot": {"checksum": "...", "updated_at": "...", "version": 1}
    }
}
```

## Client Implementation

### New Files

```
renpy/common/00cloud.rpy       # Cloud save screens and actions
renpy/cloudsync.py             # Sync engine
renpy/cloudauth.py             # OAuth flow handler
```

### OAuth Browser Flow

1. User clicks "Sign in with Discord"
2. Open system browser to `cloud.okapy.li/auth/discord?redirect=okapy://callback`
3. User authenticates with Discord
4. Server redirects to `okapy://callback?token=JWT`
5. Ren'Py handles custom URL scheme, stores JWT in persistent

### Sync Engine

```python
class CloudSync:
    def __init__(self):
        self.token = persistent.cloud_token
        self.auto_sync = persistent.cloud_auto_sync

    def sync_on_save(self, slot):
        """Called after every save if auto_sync enabled."""
        if self.auto_sync and self.token:
            self.upload_save(slot)

    def sync_on_load(self):
        """Called on game start if auto_sync enabled."""
        if self.auto_sync and self.token:
            conflicts = self.check_conflicts()
            if conflicts:
                renpy.call_screen("cloud_conflict", conflicts)
            else:
                self.download_newer()

    def check_conflicts(self):
        """Compare local and remote save metadata."""
        local = self.get_local_metadata()
        remote = self.get_remote_metadata()
        return self.detect_conflicts(local, remote)
```

### UI Screens

```renpy
screen cloud_settings():
    # Toggle auto-sync
    # Sign in/out buttons
    # Storage usage display
    # Manual sync button

screen cloud_conflict(conflicts):
    # List conflicting saves
    # For each: Keep Local | Keep Cloud | Keep Both

screen cloud_login():
    # Discord / GitHub / Google buttons
    # "Sign in to sync saves across devices"
```

### Config Variables

```python
config.has_cloud_sync = True
config.cloud_server = "https://cloud.okapy.li"
config.cloud_auto_sync_default = False
config.cloud_max_save_size = 10 * 1024 * 1024  # 10 MB per save
```

## Server Implementation

### Tech Stack

- **Framework:** FastAPI (Python)
- **Database:** PostgreSQL
- **Object Storage:** S3-compatible (MinIO self-hosted or Cloudflare R2)
- **Cache/Sessions:** Redis
- **Auth:** python-jose for JWT, authlib for OAuth

### Deployment

- Docker container behind Cloudflare
- PostgreSQL managed or self-hosted
- Object storage for save files (encrypted at rest)

## Security Considerations

- All saves encrypted client-side before upload (reuse libhydrogen)
- Server never sees plaintext save data
- Encryption key derived from user's OAuth ID + game ID
- JWT tokens with short expiry (1 hour), refresh tokens for persistence
- Rate limiting on all endpoints
- CORS restricted to Ren'Py user-agent

## Implementation Phases

### Phase 1: Server MVP
- [ ] FastAPI project setup
- [ ] OAuth integration (Discord first)
- [ ] User management endpoints
- [ ] Basic save CRUD endpoints
- [ ] PostgreSQL schema
- [ ] S3 storage integration

### Phase 2: Client Integration
- [ ] OAuth browser flow in Ren'Py
- [ ] Token storage in persistent
- [ ] Manual upload/download
- [ ] Cloud settings screen

### Phase 3: Auto Sync
- [ ] Background sync thread
- [ ] Conflict detection
- [ ] Conflict resolution UI
- [ ] Sync on save/load hooks

### Phase 4: Polish
- [ ] Save history/versioning
- [ ] Storage quota management
- [ ] Multiple OAuth providers
- [ ] Device management UI

## Estimated Effort

| Component | Effort | Notes |
|-----------|--------|-------|
| Server API | 2-3 days | FastAPI + OAuth + storage |
| Database schema | 0.5 day | Simple models |
| Client sync engine | 2-3 days | Background sync, conflict detection |
| OAuth browser flow | 1 day | Platform-specific URL handling |
| UI screens | 1-2 days | Login, settings, conflicts |
| Testing | 2 days | Multi-device scenarios |
| **Total** | **~10 days** | |

## Open Questions

1. Should we support the old sync.renpy.org as fallback for games that don't use Oka'Py cloud?
2. Storage limits per user? (100 MB default seems reasonable)
3. Should save history be time-limited or count-limited?
4. Do we want a web UI for managing saves outside the game?
