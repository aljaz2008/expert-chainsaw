# Docker Networking Foundations

## Bridge Networks

### Create a user-defined bridge

Theory: user-defined bridge networks provide DNS-based service discovery for attached containers.

```bash
docker network create lab_bridge
```

#### Expected behavior

The Docker network named `lab_bridge` exists after creation.

#### Cleanup

Remove the `lab_bridge` network.

```bash
docker network rm lab_bridge
```

## Published Ports

### Start an nginx container

```bash
docker run -d --name lab_web -p 8088:80 nginx:alpine
```

#### Expected behavior

The container is running and port 8088 is reachable from the host.

```bash
docker rm -f lab_web
```

## Linux Firewall Observability

### Inspect DOCKER-USER

```bash
iptables -S DOCKER-USER
```

#### Expected behavior

On native Linux with iptables support, the DOCKER-USER chain is displayed. On Docker Desktop this is unsupported or differs from native Linux.
