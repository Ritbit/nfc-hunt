# Deployment

The app runs as **uWSGI behind nginx**, managed by systemd. Deployed code lives
at `/var/www/nfc_hunt`; secrets live in `/etc/nfc_hunt.env` (never in the repo).

## Current target

Test VM: `root@10.255.253.20` (CentOS Stream 10, aarch64).

## Redeploy (normal case)

```bash
./deploy/deploy.sh                # or: ./deploy/deploy.sh user@host
```

Syncs the working tree (excluding venv/db/tests), installs any new
requirements, refreshes configs, restarts `nfc_hunt` + `nginx`, and runs a
health check.

## First-time setup on a fresh RHEL-family host

```bash
dnf install -y python3-pip python3-devel gcc pcre2-devel rsync nginx
mkdir -p /var/www/nfc_hunt && rsync -az <repo>/ root@host:/var/www/nfc_hunt/
cd /var/www/nfc_hunt && python3 -m venv venv
./venv/bin/pip install -r requirements.txt
pip3 install uwsgi            # system binary — SELinux blocks venv exec from systemd

# Secrets (required — app refuses to start without ADMIN_PASSWORD)
printf 'ADMIN_PASSWORD=%s\nFLASK_SECRET_KEY=%s\n' "$(pwgen 16 1)" "$(pwgen 48 1)" > /etc/nfc_hunt.env
chmod 600 /etc/nfc_hunt.env

cp deploy/nfc_hunt.ini /etc/uwsgi.d/
cp deploy/nfc_hunt.conf /etc/nginx/conf.d/
cp deploy/nfc_hunt.service /etc/systemd/system/
chown -R nginx:nginx /var/www/nfc_hunt
systemctl daemon-reload && systemctl enable --now nfc_hunt nginx
firewall-cmd --permanent --add-service=http && firewall-cmd --reload
```

## SELinux notes

If SELinux is enforcing, additionally:

```bash
setsebool -P httpd_can_network_connect on
semanage fcontext -a -t httpd_sys_content_t "/var/www/nfc_hunt(/.*)?"
restorecon -Rv /var/www/nfc_hunt
# Then generate a module for the unix-socket connectto denial:
grep avc /var/log/audit/audit.log | audit2allow -M nfc_hunt && semodule -i nfc_hunt.pp
```

## Operational notes

- Admin password is stored at `/root/nfc_hunt_admin_password.txt` on the server.
- Logs: `journalctl -u nfc_hunt` and `/var/log/nginx/error.log`.
- Database is `treasure_hunt.db` in the app dir; excluded from deploys.
- uWSGI runs **1 process with threads** — required for SocketIO session
  affinity. Do not raise `processes` in `nfc_hunt.ini`.
- HTTPS is required for phone NFC handlers to open scanned URLs — add TLS
  (certbot or a reverse proxy in front) before a real event.
