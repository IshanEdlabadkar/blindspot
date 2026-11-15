# Self-hosting a document server with HTTPS (nginx or Apache + Let's Encrypt)

The four hosted servers run on Render, which handles HTTPS itself (managed certificates, HTTP redirected
to HTTPS), so none of this is needed there. Use this when a provider runs a document server on its own
machine: a VM, a lab server, a box at the venue.

The document server listens on loopback only; nginx (or Apache) in front of it does TLS, redirects HTTP
to HTTPS, caps request sizes and timeouts, rate-limits per client, and keeps **no access log** (the
server's own log has four fields; a web server would otherwise record every address and path).

Clients refuse plain `http://` to any server that isn't on the same machine, so HTTPS is required.

## Steps (Ubuntu 24.04, nginx)

```bash
sudo apt install nginx certbot
# 1. The document server, loopback only (corpus from Databricks, or a local folder):
BLIND_RAG_DATA_URL=https://<workspace>/api/2.0/fs/files/Volumes/workspace/default/blindrag/<id>/ \
BLIND_RAG_DATA_AUTH="Bearer <token>" BLIND_RAG_TOKEN_MODE=0 \
  ./crypto-server/crypto-server -addr 127.0.0.1:8080

# 2. nginx config: replace docs.example.org with your domain (its DNS must point at this machine)
sed 's/docs.example.org/YOUR.DOMAIN/g' deploy/selfhost/nginx.conf | sudo tee /etc/nginx/conf.d/blind-rag.conf

# 3. First certificate: comment out the whole "listen 443" server block, then
sudo mkdir -p /var/www/certbot && sudo nginx -t && sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/certbot -d YOUR.DOMAIN
#    uncomment the 443 block, then
sudo nginx -t && sudo systemctl reload nginx

# 4. Renewal: certbot installs a timer; make nginx pick up renewed certificates:
echo 'systemctl reload nginx' | sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
sudo certbot renew --dry-run

# 5. Check from another machine, then pin it (it must also be in servers.remote.json):
curl -sI https://YOUR.DOMAIN/v1/manifest | grep -i strict-transport
python3 scripts/check_servers.py --pin
```

nginx rate-limits per client here (20 question requests/s with a burst of 200; 20 big downloads/min with
a burst of 12; 16 connections). It overwrites `X-Forwarded-For` with the real address, so clients can't
spoof it. You can also turn on the server's own limiter and penalty box: `BLIND_RAG_RATE_LIMIT=1`.

## Apache instead of nginx

```bash
sudo apt install apache2 certbot python3-certbot-apache
sudo a2enmod ssl proxy proxy_http headers rewrite
sed 's/docs.example.org/YOUR.DOMAIN/g' deploy/selfhost/apache.conf | sudo tee /etc/apache2/sites-available/blind-rag.conf
sudo a2ensite blind-rag && sudo certbot --apache -d YOUR.DOMAIN   # gets the certificate and reloads Apache
```

Apache has no per-client rate limit as simple as nginx's, so start the document server with
`BLIND_RAG_RATE_LIMIT=1` (the server trusts the `X-Forwarded-For` Apache overwrites).

## Tested

Both configs pass `nginx -t` / `apache2ctl -t` (nginx 1.24, Apache 2.4 on Ubuntu 24.04). The nginx setup was
run end to end with a self-signed certificate: HTTP redirected to HTTPS, HSTS sent, TLS 1.1 refused, the
manifest's hint URLs came back as `https://`, the encrypted pipeline ran with 0 errors and exact scores
(real PIR and download), the download limit refused the 13th fetch-store request, and the access log
stayed empty.
