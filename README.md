# stroke-order-memorize

## Deployment

Create a dedicated system user and copy the app:

```bash
sudo useradd --system --home /var/lib/stroke-memorize --create-home --shell /sbin/nologin stroke-memorize
sudo cp -r . /var/lib/stroke-memorize
sudo chown -R stroke-memorize:stroke-memorize /var/lib/stroke-memorize
```

Copy your `.env` file to `/var/lib/stroke-memorize/.env`, then install and start the service:

```bash
sudo cp stroke-memorize.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stroke-memorize
```