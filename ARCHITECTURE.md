# Architecture — Real-Time WebSocket Chat

## System context

The system exposes one public application endpoint through an Azure Linux VM. Browser
clients use normal HTTP to load the frontend and a persistent WebSocket connection to
exchange chat messages. Nginx is the only publicly exposed application container.

```mermaid
flowchart LR
    Clients["Browser clients"]
    Azure["Azure public IP<br/>20.204.44.138"]
    Nginx["Nginx reverse proxy<br/>Container port 80"]
    API["FastAPI WebSocket backend<br/>Container port 8000"]

    Clients -->|"GET /"| Azure
    Clients <-->|"WebSocket /ws"| Azure
    Azure --> Nginx
    Nginx -->|"Docker DNS: backend:8000"| API
```

## Deployment architecture

```mermaid
flowchart TB
    Internet["Internet"]

    subgraph Azure["Microsoft Azure"]
        NSG["Network Security Group<br/>Allow TCP 80 and TCP 22"]
        PublicIP["Public IP<br/>20.204.44.138"]

        subgraph VM["Ubuntu Linux VM"]
            SSH["SSH service<br/>Port 22"]
            Docker["Docker Engine"]

            subgraph Network["Compose bridge network"]
                Nginx["chat-nginx<br/>nginx:alpine<br/>80:80"]
                Backend["chat-backend<br/>Python 3.11 / Uvicorn<br/>expose 8000"]
            end

            Frontend["./frontend<br/>read-only bind mount"]
            Config["./nginx.conf<br/>read-only bind mount"]
        end
    end

    Internet --> NSG
    NSG --> PublicIP
    PublicIP --> Nginx
    PublicIP --> SSH
    Docker --> Network
    Frontend --> Nginx
    Config --> Nginx
    Nginx -->|"HTTP/1.1 WebSocket proxy"| Backend
```

## Component responsibilities

| Component | Responsibility |
|---|---|
| Azure Network Security Group | Permits public HTTP and controlled SSH access |
| Azure Ubuntu VM | Hosts Docker Engine and the checked-out Git repository |
| Docker Compose | Creates services, shared network, mounts, and restart policies |
| Nginx container | Serves the frontend and proxies `/ws` |
| FastAPI container | Accepts WebSockets and broadcasts messages |
| GitHub Actions | Validates, builds, smoke-tests, and deploys each `main` push |

## Network and port model

```text
Browser
   |
   | HTTP :80 and WebSocket :80/ws
   v
Azure NSG and public IP
   |
   v
Nginx container :80
   |
   | Docker Compose bridge network
   | backend:8000
   v
FastAPI container :8000
```

| Source | Destination | Port | Exposure |
|---|---|---:|---|
| Browser | Azure VM/Nginx | `80` | Public |
| GitHub Actions/administrator | Azure SSH service | `22` | Public, authenticated |
| Nginx container | Backend service | `8000` | Internal Compose network only |

The Compose service name `backend` provides stable service discovery. Container IP
addresses can change without requiring an Nginx configuration change.

## HTTP request flow

1. The browser requests `GET /` from the Azure public IP.
2. Azure's Network Security Group permits TCP port `80`.
3. Docker forwards VM port `80` to the Nginx container.
4. Nginx reads `index.html` from its read-only frontend mount.
5. Nginx returns the static frontend to the browser.

## WebSocket connection flow

```mermaid
sequenceDiagram
    participant B as Browser
    participant N as Nginx
    participant F as FastAPI

    B->>N: GET /ws with Upgrade: websocket
    N->>F: Proxy to backend:8000/ws
    F-->>N: 101 Switching Protocols
    N-->>B: 101 Switching Protocols
    B->>F: WebSocket message through Nginx
    F-->>B: Broadcast message through Nginx
```

Nginx uses HTTP/1.1 and forwards both WebSocket upgrade headers:

```nginx
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

Long proxy read and send timeouts prevent Nginx from prematurely closing an otherwise
healthy persistent WebSocket connection.

## CI/CD architecture

```mermaid
sequenceDiagram
    actor Developer
    participant GH as GitHub
    participant CI as GitHub Actions
    participant VM as Azure VM
    participant DC as Docker Compose

    Developer->>GH: Push to main
    GH->>CI: Trigger workflow
    CI->>CI: Validate Compose
    CI->>CI: Build and start containers
    CI->>CI: HTTP smoke test
    CI->>VM: Password-authenticated SSH
    VM->>GH: Fetch and pull main
    VM->>DC: Build and recreate services
    DC-->>VM: Containers running
    CI->>VM: HTTP smoke test on 127.0.0.1
    VM-->>CI: Deployment successful
```

The deployment job runs only if the CI job succeeds. GitHub Actions secrets provide
the VM hostname, user, password, SSH port, host key, and application directory.
Concurrency permits only one active production deployment.

## Availability and restart behavior

Both containers use `restart: always`. Docker recreates the desired running state
after container crashes and starts the containers again when the VM and Docker daemon
restart.

This deployment uses a single backend instance with in-memory connection state. It is
appropriate for this assignment and a small demonstration. Horizontal scaling would
require shared pub/sub state, such as Redis, plus a load balancer configured for
WebSocket traffic.

## Security boundary

- Only Nginx port `80` is published for application traffic.
- Backend port `8000` remains private to the Compose network.
- Deployment credentials are stored as GitHub Actions secrets.
- SSH host-key verification protects the workflow from connecting to an unexpected VM.
- Frontend and Nginx configuration mounts are read-only.
- HTTPS, `wss://`, and key-based SSH are recommended production improvements.

