# WireGuard y entrada OVH

## Túnel privado en los hosts

Si ya tienes VPN entre ambos servidores, reutilízala y ajusta `.env`; los ejemplos
no sustituyen una conexión existente. Si no, instala `wireguard-tools` en ambos
Debian y genera una clave distinta en cada host:

```bash
sudo apt update
sudo apt install wireguard-tools
sudo install -d -m 700 /etc/wireguard
sudo sh -c 'set -eu; umask 077; test ! -e /etc/wireguard/media.key; test ! -e /etc/wireguard/media.pub; wg genkey > /etc/wireguard/media.key; wg pubkey < /etc/wireguard/media.key > /etc/wireguard/media.pub'
sudo cat /etc/wireguard/media.pub
```

Ese comando de generación es para una instalación nueva; **no lo repitas sobre
claves existentes**. Intercambia solo las claves públicas. Copia los valores
privados localmente a las plantillas con `sudoedit`, nunca al repositorio:

- Casa: `examples/wireguard/home.conf.example` → `/etc/wireguard/wg-media.conf`.
- OVH: `examples/wireguard/ovh.conf.example` → `/etc/wireguard/wg-media.conf`.

En casa pon endpoint público de OVH y keepalive. En OVH permite **UDP 51820** en
el firewall del host y el de OVH, si está activado. No necesitas entrada UDP en
el router de casa; casa inicia la conexión. Las plantillas enrutan solo las IP
de los peers; no incluyen `0.0.0.0/0`, LAN completas ni subredes Docker/Kubernetes.
Comprueba que `10.77.0.0/24` no coincide con ninguna red existente.

```bash
sudo chmod 600 /etc/wireguard/wg-media.conf
sudo systemctl enable --now wg-quick@wg-media
sudo wg show wg-media
ip address show wg-media
```

No hace falta convertir casa/OVH en routers de toda la LAN. El proxy conecta a
puertos publicados en la IP del host. Si Traefik está en Docker, comprueba que
su bridge tiene salida hacia WireGuard y que el firewall permite ese flujo.
La política de forwarding del host debe permitir las redes Docker necesarias;
no actives forwarding global ni añadas reglas amplias sin revisar tu firewall.

## Restringir los puertos al peer OVH

Publicar en una IP concreta no equivale a filtrar por interfaz: con forwarding,
otra red que tenga una ruta hacia esa IP podría alcanzarla. Antes del overlay,
limita 8096/5055 a la interfaz WireGuard y al peer OVH. Para el backend iptables
habitual de Docker (también iptables-nft), este ejemplo añade reglas a DOCKER-USER
sin vaciar reglas existentes. Cambia los tres valores a los reales:

```bash
media_home_wg_ip=10.77.0.2
media_ovh_wg_ip=10.77.0.1
media_wg_interface=wg-media
sudo iptables -S DOCKER-USER
for media_port in 8096 5055; do
  sudo iptables -I DOCKER-USER 1 -p tcp ! -i "$media_wg_interface" \
    -m conntrack --ctdir ORIGINAL --ctorigdst "$media_home_wg_ip" --ctorigdstport "$media_port" -j DROP
  sudo iptables -I DOCKER-USER 1 -p tcp ! -s "$media_ovh_wg_ip" \
    -m conntrack --ctdir ORIGINAL --ctorigdst "$media_home_wg_ip" --ctorigdstport "$media_port" -j DROP
done
```

Si DOCKER-USER no existe, revisa primero el backend: estos comandos no son para
el backend nftables nativo de Docker. Configura una política equivalente mediante
tu firewall, usando la interfaz y el origen del túnel. Persistencia: integra las
reglas con tu gestión de firewall y carga tras arrancar Docker; prueba un reinicio.
Este proyecto presupone redes Docker NAT normales, sin `allow-direct-routing` ni
`nat-unprotected`. No cambies el daemon ni vacíes iptables para aplicar el ejemplo.
Verifica que SSH por localhost sigue funcionando y que el peer OVH pasa mientras
la LAN no alcanza los puertos de la IP del túnel.

Referencia: [Docker y DOCKER-USER](https://docs.docker.com/engine/network/firewall-iptables/).

En casa, después del bootstrap, ejecuta el overlay público del README. Desde OVH:

```bash
curl -fsS http://10.77.0.2:8096/health
curl -fsS http://10.77.0.2:5055/api/v1/settings/public
```

Esas rutas de salud son públicas por diseño y **no prueban autenticación**. Para
confirmar el túnel revisa también el handshake WireGuard y los contadores de tráfico.

## DNS y Traefik existente

1. Crea registros **A** para ambos subdominios apuntando a la IP de OVH. Añade AAAA
   únicamente si tienes IPv6 funcional hasta ese Traefik. Elimina registros erróneos.
2. En `.env` configura los dominios reales, `HOME_WG_IP` y los nombres reales de
   entrypoints/resolver de tu Traefik (`web`, `websecure`, `letsencrypt` son ejemplos).
3. Genera reglas en la copia del proyecto de casa u OVH:

```bash
./stack edge-config --accounts-configured
```

4. Copia **solo** `edge/dynamic/media.yml` a la carpeta del proveedor `file` que tu
   Traefik tiene montada. Ejemplo si ese proveedor observa `/opt/traefik/config`:

```bash
sudo install -m 644 edge/dynamic/media.yml /opt/traefik/config/media.yml
```

La configuración estática debe tener esos entrypoints y resolver ACME, y observar
la carpeta. Si utiliza `providers.file.filename` para un archivo único, integra
las entradas `routers`, `middlewares` y `services` en ese archivo o cambia a
`directory` siguiendo tu configuración: copiar un segundo archivo no basta.
No sobrescribas reglas ajenas ni pegues un segundo bloque `http:` en el mismo YAML.

El archivo añade routers HTTP→HTTPS por dominio y routers HTTPS hacia la IP privada
de casa. Traefik soporta WebSocket sin un middleware adicional. No incluye Basic Auth
extra, para conservar la compatibilidad de los clientes Jellyfin con su login nativo.
Si existe un proxy previo, confía solo en sus IP verificadas para forwarded headers.
Evita registrar query strings/cabeceras de autenticación: algunos clientes multimedia
pueden transportar tokens en las URL. El proxy opcional no activa access logs.

## Traefik opcional incluido

Úsalo solo si OVH no tiene un proxy ocupando 80/443. Copia el proyecto a OVH,
ejecuta `./stack init` si falta `.env` y configura los mismos dominios e IP de casa,
un email ACME real y los nombres `web`, `websecure`, `letsencrypt`:

```bash
./stack check
./stack lock --target edge
./stack edge-config --accounts-configured
sudo ./stack prepare-edge
./stack config --target edge
./stack up --target edge --accounts-configured
./stack status --target edge
```

Este Compose usa el proveedor file y **no monta Docker socket**. ACME se guarda en
`edge/acme/acme.json` con propietario 65532:65532 y permisos 0600; respáldalo de
forma privada. Los proyectos Compose de casa y OVH tienen nombres distintos.
El puerto interno de ping de Traefik no se publica. El túnel permanece en el host.

No cambies las IP del túnel con el proxy activo sin regenerar reglas y revisar los
Known Proxies de Jellyfin. Antes de actualizar Traefik, guarda ACME y el lock de OVH.

## Verificación de acceso real

- Desde una red externa, abre ambos subdominios en una ventana privada. Comprueba
  certificado válido, redirección HTTP→HTTPS y que la biblioteca exige login.
- Entra con una cuenta normal y verifica que no puede administrar otras cuentas.
- Reproduce un vídeo y prueba adelantarlo; comprueba el cliente de móvil/TV si lo usas.
- Comprueba en OVH que **no** alcanzas casa en 7878, 8989, 9696, 6767 ni 8080 por WireGuard.
- Verifica que el daemon Docker no está publicado y que no hay mappings wildcard
  añadidos en otro Compose o servicio del host.
- Si WireGuard cae, se interrumpe el acceso remoto. Las descargas y el acceso por
  SSH/local siguen dependiendo del estado de casa y su red.

Referencias: [Jellyfin reverse proxy](https://jellyfin.org/docs/general/post-install/networking/reverse-proxy/),
[Traefik file provider](https://doc.traefik.io/traefik/providers/file/),
[WireGuard quick start](https://www.wireguard.com/quickstart/).
