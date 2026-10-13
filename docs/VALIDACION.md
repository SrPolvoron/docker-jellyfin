# Validación y estado del proyecto

Fecha: 2026-10-13. Entrega orientada a **desarrollo e instalación supervisada**.
No se ha desplegado en los servidores de casa/OVH ni publicado en GitHub.

## Comprobaciones ejecutadas

| Comprobación | Resultado |
|---|---|
| `python3 -m unittest discover -s tests -v` | 26 pruebas correctas |
| `python3 tests/check_compose.py` | Correcto: YAML y contratos de despliegue |
| Parseado AST compatible con Python 3.10 | Correcto |
| `python3 -m compileall -q scripts tests` | Correcto |
| `sh -n stack` | Correcto |

Las pruebas cubren rechazo de interpolaciones de shell, dominios que podrían
inyectar reglas, UID root, binds wildcard, rutas críticas/solapadas/simbólicas,
publicación sin declaración de bootstrap o sin dirección del túnel, digests
inválidos, fallo parcial de resolución, aislamiento de proyectos Compose,
protección frente a overrides de entorno, backup sin sobrescritura y reinicio
tras un fallo parcial de parada. La prueba de backup crea e inspecciona un TAR real;
las llamadas a Docker en estas pruebas están simuladas.

La comprobación YAML analiza anchors, bind mounts, permisos, capacidades, redes,
ports, overlays, dispositivos GPU, reglas Traefik generadas y rutas /32 WireGuard.
Emplea digests ficticios únicamente dentro del test, que no se distribuyen como lock.
**No es un validador oficial completo de Compose ni prueba que arranquen las imágenes.**

## Limitaciones del entorno de creación

No hay Docker Engine ni CLI Compose disponibles aquí. No se han descargado ni
ejecutado las imágenes, ni comprobado registros, listeners, SQLite real, s6,
transcodificación o conexiones entre aplicaciones. Los digests reales se resuelven
en tu servidor mediante `./stack lock`; no hay un lock de producción inventado.
También se ha ejecutado la CLI real para init, check, edge-config y el rechazo de
arranque sin lock en una copia temporal. La asignación real de propietarios de
prepare no pudo comprobarse: este entorno devuelve EINVAL al intentar chown a
UID/GID 1000, también sobre un directorio temporal fuera del proyecto.

La configuración no contiene tus dominios, IP reales, capacidad del servidor,
fuentes ni credenciales: debes ajustar `.env` y las interfaces durante el setup.
WireGuard y las reglas de firewall se configuran siguiendo la guía, no mediante
un instalador que modifique el host automáticamente.

## Prueba de aceptación en Debian y OVH

1. Revisa `.env`; ejecuta check, prepare, lock y **`./stack config`**. La validación
   nativa de Compose debe finalizar sin errores antes de crear contenedores.
2. Arranca en privado. `./stack status` debe mostrar Jellyfin/Seerr saludables y
   los demás servicios activos sin bucles de reinicio. Revisa permisos y logs.
   Mantén las protecciones; diagnostica cualquier incompatibilidad con la imagen
   resuelta en lugar de añadir privilegios o desactivar autenticación a ciegas.
3. Configura cuentas y conexiones siguiendo CONFIGURACION.md. Prueba credenciales
   incorrectas y cuentas con diferentes bibliotecas; deben negar acceso correctamente.
4. Con un archivo de prueba o una descarga de una fuente que hayas configurado,
   verifica importación, detección en Jellyfin y reproducción. Si usas hardlinks,
   compara inode/número de enlaces del archivo descargado y el importado en el host.
5. Haz un backup, inspecciónalo en un directorio temporal privado y confirma que
   las aplicaciones previamente activas vuelven a estar disponibles. Programa
   una restauración de prueba en un entorno separado antes de depender de la copia.
6. Configura WireGuard y el filtrado por interfaz/peer, confirma handshake y que
   OVH llega a los dos servicios y la LAN no puede alcanzar la IP del túnel.
   Ejecuta `./stack config --public`, publica en casa y configura Traefik.
7. Prueba HTTPS desde una red externa, login, WebSocket/cliente móvil si procede,
   adelantar vídeo y solicitudes. Los paneles administrativos no deben responder
   por la IP WireGuard ni por subdominios públicos.
8. Recrea el stack manteniendo --public y comprueba que permanecen cuentas,
   bibliotecas y configuraciones. Revisa recuperación después de reiniciar casa.

La herramienta no automatiza cuentas, API keys o fuentes de búsqueda. El próximo
paso es desplegar en privado y validar las imágenes reales, después habilitar OVH.

## Referencias primarias utilizadas

- [Jellyfin en contenedores](https://jellyfin.org/docs/general/installation/container/)
- [Almacenamiento de Jellyfin](https://jellyfin.org/docs/general/administration/storage/)
- [Gestión de usuarios](https://jellyfin.org/docs/general/server/users/adding-managing-users/)
- [Seerr en Docker](https://docs.seerr.dev/getting-started/docker/)
- [LSIO Radarr](https://docs.linuxserver.io/images/docker-radarr/)
- [LSIO Sonarr](https://docs.linuxserver.io/images/docker-sonarr/)
- [LSIO Prowlarr](https://docs.linuxserver.io/images/docker-prowlarr/)
- [LSIO qBittorrent](https://docs.linuxserver.io/images/docker-qbittorrent/)
- [LSIO con usuario no root](https://docs.linuxserver.io/misc/non-root/)
- [WireGuard](https://www.wireguard.com/quickstart/)
- [Traefik file provider](https://doc.traefik.io/traefik/providers/file/)
- [Docker port publishing](https://docs.docker.com/engine/network/port-publishing/)
