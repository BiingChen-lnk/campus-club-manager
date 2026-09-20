# Linux 部署配置

本目录是 Ubuntu、Nginx、Gunicorn、MySQL 部署配置示例，不包含运行中的数据库和凭据。源码来自已部署版本；公开版本通过 `DBXM_TRUSTED_HOSTS` 配置域名，部署配置中的域名已替换为 `club.example.com`。

## 目录约定

- `/opt/dbxm/current`：项目代码，可以是指向版本目录的符号链接。
- `/opt/dbxm/venv`：Python 虚拟环境。
- `/opt/dbxm/shared/.env`：实际配置，权限设为 600，由 `dbxm` 用户读取。
- `/opt/dbxm/shared/instance`：上传文件和会话文件，由 `dbxm` 用户写入。

将代码目录的 `.env` 和 `instance` 分别链接到共享目录。生产服务使用独立系统用户 `dbxm`，其余代码文件只需可读。

## 初始化

1. 安装 Python 3.12、python3-venv、MySQL 8.0 和 Nginx。
2. 创建项目专用 MySQL 数据库及账号，填写 `.env.example` 对应配置。初始化账号需有建库和建表权限。不要在网站进程中使用 MySQL root。
3. 在虚拟环境安装 `requirements-server.txt`，或使用本目录中的 `requirements-server-lock.txt` 复现部署时的完整依赖版本。
4. 在代码目录执行 `python manage.py init` 和 `python manage.py create-admin`。生产环境不建议加载演示账号。
5. 安装并检查下列配置，根据实际目录和域名调整。

| 示例文件 | 安装位置 |
| --- | --- |
| dbxm.service | /etc/systemd/system/dbxm.service |
| nginx.conf.example | /etc/nginx/sites-available/dbxm |
| dbxm-proxy.conf | /etc/nginx/snippets/dbxm-proxy.conf |
| dbxm-limits.conf | /etc/nginx/conf.d/dbxm-limits.conf |
| mysql.cnf.example | /etc/mysql/mysql.conf.d/zz-dbxm.cnf |

Nginx 示例包含 HTTPS 配置，需要先替换域名并获取相应证书；没有证书时不要直接启用 443 配置。HTTP 证书验证目录使用 `/var/www/letsencrypt`。按实际服务器环境配置证书签发和自动续期，续期成功后重载 Nginx。部署于中国内地的公开网站还需办理备案。

在实际 `.env` 中设置：

```ini
DBXM_TRUSTED_HOSTS=club.example.com,127.0.0.1,localhost
DBXM_HTTPS=1
DBXM_SECRET_KEY=replace_with_a_random_secret
```

只有 HTTPS 配置完成后才设置 `DBXM_HTTPS=1`，否则浏览器不会通过 HTTP 发送登录 Cookie。

启用站点的符号链接后执行：

```sh
nginx -t
systemctl daemon-reload
systemctl enable --now dbxm
systemctl reload nginx
```

Gunicorn 仅监听 `127.0.0.1:8000`，由本机 Nginx 代理。`wsgi.py` 信任一层代理传入的客户端 IP 和协议，因此不要将该端口直接暴露到公网。MySQL 示例同样只监听本机。

## 维护

```sh
systemctl status dbxm nginx mysql --no-pager
systemctl restart dbxm
journalctl -u dbxm -n 80 --no-pager
```

更新前备份数据库和 `instance/uploads`，保留服务器 `.env` 与共享目录。Git 仓库不提供数据备份或自动部署功能。
