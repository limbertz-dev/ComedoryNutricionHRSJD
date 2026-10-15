# Auxiliares del escenario sintético

Estos archivos están versionados en `develop`. La carpeta `qa/` no es la rama
`qa/main`. El preparador está en `scripts/preparar_escenario_sintetico.py`.

Los destinos son exclusivamente `bd_nutricion_escenario_sim` y
`bd_turnos_escenario_demo`. Integrar el código no crea bases, no cambia claves
y no inicia servicios.

Desde `comedorback/`, la habilitación manual se ejecuta así:

```powershell
.\.venv\Scripts\python ..\qa\habilitar_cocineras_escenario.py
```

Este comando resetea ambas cuentas: no ejecutarlo si ya están habilitadas.
Requiere la API local del escenario en `http://127.0.0.1:8765` y solicita
contraseñas en la consola privada. `--solo-comprobar` evita los reseteos.

Desde la raíz del repositorio, el validador se ejecuta así:

```powershell
.\comedorback\.venv\Scripts\python qa\validar_derecho_escenario.py --manifiesto qa\manifiesto_escenario_2026-10-15.json --back comedorback --api http://127.0.0.1:8765
```

Requiere las variables de conexión indicadas en el script. Sin las claves
de las cocineras, sus comprobaciones autenticadas quedan pendientes.

El manifiesto y la salida de validación son evidencia histórica del
15/10/2026 sobre el commit `5cd80fa`, anterior a esta integración. No certifican
el estado actual de las contraseñas ni que la API siga levantada. Los guiones
conservan resultados y pendientes de esa corrida; el circuito de entrega y
el QA formal no se ejecutaron durante la integración.

Validación de integración: 118 pruebas unitarias aprobadas, 3 pruebas MySQL
opt-in omitidas; sintaxis Python y JSON comprobada. No se ejecutó el
preparador ni se accedió a bases de datos.
