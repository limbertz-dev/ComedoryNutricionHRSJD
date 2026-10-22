"""Laboratorio QA: la API real del comedor con un reloj movible y un panel
para simular el lector biométrico.

    python lab.py                 base real de desarrollo (bd_nutricion + bd_proyecto_backend)
    python lab.py --base sim      base sintética (bd_nutricion_escenario_sim + bd_turnos_escenario_demo)

Abre:
    http://127.0.0.1:8000/_lab    el panel del laboratorio
    http://127.0.0.1:8000         la API de siempre (el front `npm run dev` la usa sin cambios)

Qué hace y qué no:
  · Las lecturas pasan por `registrar_marcacion()`, la misma lógica que usa la
    app: derecho, horario y duplicados los decide el servidor, no el panel.
  · Solo escribe en la base PROPIA (lecturas, asistencias, intervenciones). La
    base de turnos se lee a través de las vistas v_* y nunca se escribe.
  · Todo lo que crea queda marcado con el dispositivo `laboratorio-qa`, y
    «Limpiar» borra solo eso.
  · El reloj de NEGOCIO (`reloj.ahora`) se mueve dentro de este proceso. El de
    seguridad (`reloj.real`, tokens y bloqueo de login) sigue siendo el real.
  · Nada de esto vive en comedorback/app: las rutas /_lab solo existen cuando
    se arranca con este script.
"""

import argparse
import json
import os
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
RAIZ = CARPETA.parents[1]
BACK = RAIZ / "comedorback"
PANEL = CARPETA / "panel"
ESTADO = CARPETA / "estado.json"

BASES = {
    "real": ("bd_nutricion", "bd_proyecto_backend"),
    "sim": ("bd_nutricion_escenario_sim", "bd_turnos_escenario_demo"),
}
DISPOSITIVO = "laboratorio-qa"
CUENTAS_LIMITE = 50


# --- reloj -------------------------------------------------------------------


class Reloj:
    """Hora de negocio del laboratorio.

    real       la hora del servidor, sin tocar
    pausado    queda quieta en `ancla`
    corriendo  avanza desde `ancla` al ritmo real
    """

    MODOS = ("real", "pausado", "corriendo")

    def __init__(self):
        self._cerrojo = threading.Lock()
        self.modo = "real"
        self.ancla: datetime | None = None
        self.ancla_real: datetime | None = None

    def ahora(self) -> datetime:
        with self._cerrojo:
            real = datetime.now()
            if self.modo == "real" or self.ancla is None:
                return real
            if self.modo == "pausado":
                return self.ancla
            return self.ancla + (real - self.ancla_real)

    def fijar(self, momento: datetime | None, modo: str) -> None:
        if modo not in self.MODOS:
            raise ValueError("Modo de reloj desconocido")
        if modo != "real" and momento is None:
            raise ValueError("Falta la fecha y hora")
        with self._cerrojo:
            self.modo = modo
            self.ancla = None if modo == "real" else momento
            self.ancla_real = None if modo == "real" else datetime.now()

    def como_dict(self) -> dict:
        return {
            "modo": self.modo,
            "ancla": self.ancla.isoformat() if self.ancla else None,
        }

    def restaurar(self, datos: dict) -> None:
        try:
            ancla = datetime.fromisoformat(datos["ancla"]) if datos.get("ancla") else None
            self.fijar(ancla, datos.get("modo", "real"))
        except (KeyError, TypeError, ValueError):
            self.fijar(None, "real")


RELOJ = Reloj()


def leer_estado() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar_estado(**cambios) -> None:
    datos = {**leer_estado(), **cambios}
    ESTADO.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


# --- configuración del proceso ----------------------------------------------


def preparar_entorno(base: str) -> None:
    """Fija las bases ANTES de importar la app: su configuración se lee una vez."""
    propia, turnos = BASES[base]
    for variable, valor in (("DB_NAME", propia), ("DB_NAME_TURNOS", turnos)):
        actual = os.environ.get(variable)
        if actual and actual != valor:
            raise SystemExit(f"{variable}={actual} no coincide con la base «{base}» ({valor}).")
        os.environ[variable] = valor
    os.environ["ENTORNO"] = "desarrollo"
    os.environ.setdefault("DB_HOST", "127.0.0.1")
    os.environ.setdefault("DB_PORT", "3306")
    os.environ.setdefault("DB_USER", "root")
    sys.path.insert(0, str(BACK))
    os.chdir(BACK)


# --- rutas del laboratorio ---------------------------------------------------


def crear_router():
    """Se importa después de `preparar_entorno`."""
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import FileResponse
    from pydantic import BaseModel
    from sqlalchemy import delete, func, or_, select, text

    from app.consultas.derecho import _consulta_base
    from app.consultas.horarios import estado_en, ventanas_del_dia
    from app.consultas.perfiles import categoria_permitida
    from app.consultas.servicio import comida_de_referencia
    from app.core.config import config
    from app.core.db import SesionLocal
    from app.logica.autenticacion import bloqueado_hasta
    from app.logica.marcacion import registrar_marcacion, resolver_comida_en_curso
    from app.modelos.comedor import Asistencia, IntervencionLectura, LecturaBiometrica
    from app.modelos.heredados import Comensal, ComidaPorTurno
    from app.modelos.usuarios import IntentoLogin, UsuarioSistema

    router = APIRouter(prefix="/_lab", include_in_schema=False)

    def solo_local(peticion: Request) -> None:
        if peticion.client is None or peticion.client.host not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(403, "El laboratorio solo responde en esta computadora.")

    @dataclass
    class Servicio:
        comida_id: int | None
        comida: str | None
        fecha_comida: date | None
        vigente: bool

    def servicio_actual(sesion, momento: datetime) -> Servicio:
        vigente = resolver_comida_en_curso(sesion, momento)
        referencia = vigente or comida_de_referencia(sesion, momento)
        if referencia is None:
            return Servicio(None, None, None, False)
        return Servicio(referencia.comida_id, referencia.comida, referencia.fecha_comida, vigente is not None)

    def ids_con_derecho(servicio: Servicio):
        return (
            _consulta_base()
            .with_only_columns(ComidaPorTurno.usuario_id, maintain_column_froms=True)
            .where(ComidaPorTurno.comida_id == servicio.comida_id)
            .where(ComidaPorTurno.fecha_comida == servicio.fecha_comida)
            .distinct()
        )

    def ids_que_comieron(servicio: Servicio):
        return select(Asistencia.usuario_id).where(
            Asistencia.comida_id == servicio.comida_id,
            Asistencia.fecha_comida == servicio.fecha_comida,
        )

    def lecturas_lab():
        return select(LecturaBiometrica.id).where(LecturaBiometrica.dispositivo == DISPOSITIVO)

    def horarios_del_dia(sesion, momento: datetime) -> list[dict]:
        filas = []
        for comida in ventanas_del_dia(sesion, momento.date()):
            ventana = comida.ventanas[0]
            sugerida = min(ventana.inicio + timedelta(minutes=30), ventana.fin - timedelta(minutes=1))
            filas.append({
                "comida_id": comida.comida_id,
                "comida": comida.comida,
                "inicio": ventana.inicio.strftime("%H:%M"),
                "fin": comida.ultima.fin.strftime("%H:%M"),
                "sugerida": sugerida.isoformat(timespec="seconds"),
                "estado": estado_en(comida.ventanas, momento),
            })
        return filas

    def marcar(sesion, usuario_id: int | None) -> dict:
        resultado = registrar_marcacion(
            sesion, usuario_id=usuario_id, dispositivo=DISPOSITIVO, metodo="biometrico",
        )
        datos = asdict(resultado)
        if datos.get("fecha_comida"):
            datos["fecha_comida"] = datos["fecha_comida"].isoformat()
        return datos

    # --- panel ---

    @router.get("")
    @router.get("/")
    def panel(peticion: Request):
        solo_local(peticion)
        return FileResponse(PANEL / "index.html", headers={"Cache-Control": "no-store"})

    fuentes = (RAIZ / "comedorfront/node_modules/@fontsource/nunito").resolve()

    @router.get("/sistema/{ruta:path}")
    def sistema(ruta: str, peticion: Request):
        """Los tokens y la fuente de la app: el panel se ve como el resto del sistema."""
        solo_local(peticion)
        if ruta == "tokens.css":
            archivo = RAIZ / "comedorfront/src/styles/tokens.css"
        else:
            archivo = (fuentes / ruta).resolve()
            if not archivo.is_relative_to(fuentes) or archivo.suffix not in (".css", ".woff2", ".woff"):
                raise HTTPException(404)
        if not archivo.is_file():
            raise HTTPException(404)
        return FileResponse(archivo)

    @router.get("/panel.{extension}")
    def activo(extension: str, peticion: Request):
        solo_local(peticion)
        tipos = {"css": "text/css", "js": "text/javascript"}
        if extension not in tipos:
            raise HTTPException(404)
        return FileResponse(PANEL / f"panel.{extension}", media_type=tipos[extension],
                            headers={"Cache-Control": "no-store"})

    # --- estado y reloj ---

    @router.get("/api/estado")
    def estado(peticion: Request):
        solo_local(peticion)
        momento = RELOJ.ahora()
        with SesionLocal() as sesion:
            servicio = servicio_actual(sesion, momento)
            con_derecho = pendientes = 0
            if servicio.comida_id is not None:
                ids = ids_con_derecho(servicio).subquery()
                con_derecho = sesion.execute(select(func.count()).select_from(ids)).scalar_one()
                pendientes = sesion.execute(
                    select(func.count()).select_from(ids)
                    .where(ids.c.usuario_id.not_in(ids_que_comieron(servicio)))
                ).scalar_one()
            lecturas = sesion.execute(
                select(func.count()).select_from(lecturas_lab().subquery())
            ).scalar_one()
            entregas = sesion.execute(
                select(func.count(Asistencia.id)).where(Asistencia.lectura_id.in_(lecturas_lab()))
            ).scalar_one()
            return {
                "base": {"propia": config.db_name, "turnos": config.db_name_turnos},
                "reloj": {**RELOJ.como_dict(), "momento": momento.isoformat(timespec="seconds"),
                          "real": datetime.now().isoformat(timespec="seconds")},
                "servicio": {**asdict(servicio),
                             "fecha_comida": servicio.fecha_comida.isoformat() if servicio.fecha_comida else None,
                             "con_derecho": con_derecho, "pendientes": pendientes},
                "horarios": horarios_del_dia(sesion, momento),
                "laboratorio": {"lecturas": lecturas, "entregas": entregas},
            }

    class CuerpoReloj(BaseModel):
        modo: str
        momento: datetime | None = None

    @router.post("/api/reloj")
    def mover_reloj(cuerpo: CuerpoReloj, peticion: Request):
        solo_local(peticion)
        try:
            RELOJ.fijar(cuerpo.momento.replace(tzinfo=None) if cuerpo.momento else None, cuerpo.modo)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        guardar_estado(reloj=RELOJ.como_dict())
        return estado(peticion)

    @router.get("/api/fechas")
    def fechas_con_turnos(peticion: Request):
        """Días con gente con derecho a comer, los más cercanos al reloj primero."""
        solo_local(peticion)
        consulta = (
            _consulta_base()
            .with_only_columns(
                ComidaPorTurno.fecha_comida, ComidaPorTurno.comida_id, ComidaPorTurno.comida,
                func.count(func.distinct(ComidaPorTurno.usuario_id)),
                maintain_column_froms=True,
            )
            .group_by(ComidaPorTurno.fecha_comida, ComidaPorTurno.comida_id, ComidaPorTurno.comida)
        )
        hoy = RELOJ.ahora().date()
        with SesionLocal() as sesion:
            dias: dict[date, list] = {}
            for fecha, comida_id, comida, personas in sesion.execute(consulta).all():
                dias.setdefault(fecha, []).append(
                    {"comida_id": comida_id, "comida": comida, "personas": personas})
        cercanas = sorted(dias, key=lambda d: (abs((d - hoy).days), d))[:40]
        return [
            {"fecha": d.isoformat(), "comidas": sorted(dias[d], key=lambda c: c["comida_id"])}
            for d in sorted(cercanas)
        ]

    # --- personas ---

    @router.get("/api/personas")
    def personas(peticion: Request, q: str = "", filtro: str = "con_derecho", limite: int = 40):
        solo_local(peticion)
        if filtro not in ("con_derecho", "sin_derecho", "todos"):
            raise HTTPException(422, "Filtro desconocido")
        limite = max(1, min(limite, 100))
        momento = RELOJ.ahora()
        with SesionLocal() as sesion:
            servicio = servicio_actual(sesion, momento)
            consulta = select(
                Comensal.usuario_id, Comensal.nombre_completo, Comensal.numero_item, Comensal.categoria,
            )
            termino = q.strip()
            if termino:
                patron = f"%{termino}%"
                condiciones = [Comensal.nombre_completo.like(patron), Comensal.numero_item.like(patron)]
                if termino.isdigit():
                    condiciones.append(Comensal.usuario_id == int(termino))
                consulta = consulta.where(or_(*condiciones))
            derecho = set()
            comieron = set()
            if servicio.comida_id is not None:
                derecho = set(sesion.execute(ids_con_derecho(servicio)).scalars())
                comieron = set(sesion.execute(ids_que_comieron(servicio)).scalars())
            if filtro == "con_derecho":
                consulta = consulta.where(Comensal.usuario_id.in_(sorted(derecho) or [-1]))
            elif filtro == "sin_derecho":
                consulta = consulta.where(Comensal.usuario_id.not_in(sorted(derecho) or [-1]))
            total = sesion.execute(select(func.count()).select_from(consulta.subquery())).scalar_one()
            filas = sesion.execute(
                consulta.order_by(Comensal.nombre_completo, Comensal.usuario_id).limit(limite)
            ).all()
            return {
                "total": total,
                "personas": [
                    {
                        "id": uid, "nombre": nombre or f"Usuario {uid}", "legajo": legajo or "—",
                        "categoria": categoria or "Sin categoría",
                        "perfil_permitido": categoria_permitida(categoria),
                        "tiene_derecho": uid in derecho, "ya_comio": uid in comieron,
                    }
                    for uid, nombre, legajo, categoria in filas
                ],
            }

    # --- lector ---

    class CuerpoLectura(BaseModel):
        usuario_id: int | None = None

    @router.post("/api/lectura")
    def lectura(cuerpo: CuerpoLectura, peticion: Request):
        solo_local(peticion)
        with SesionLocal() as sesion:
            if cuerpo.usuario_id is not None and sesion.get(Comensal, cuerpo.usuario_id) is None:
                raise HTTPException(404, "Esa persona no está en el padrón.")
            return marcar(sesion, cuerpo.usuario_id)

    class CuerpoEscenario(BaseModel):
        tipo: str

    @router.post("/api/escenario")
    def escenario(cuerpo: CuerpoEscenario, peticion: Request):
        """Elige a la persona adecuada y dispara la lectura del caso."""
        solo_local(peticion)
        momento = RELOJ.ahora()
        with SesionLocal() as sesion:
            servicio = servicio_actual(sesion, momento)
            tipo = cuerpo.tipo
            if tipo == "no_reconocida":
                return {"pasos": [marcar(sesion, None)],
                        "siguiente": "En Control Biométrico (cocinera), elige la lectura e identifica a la persona."}
            if tipo == "fuera_horario":
                madrugada = datetime.combine(momento.date(), time(3, 0))
                if resolver_comida_en_curso(sesion, madrugada) is not None:
                    raise HTTPException(409, "A las 03:00 también hay servicio: revisa los horarios en Reglas.")
                persona = sesion.execute(
                    select(Comensal.usuario_id).where(Comensal.tiene_ficha == 1)
                    .order_by(Comensal.usuario_id).limit(1)
                ).scalar()
                RELOJ.fijar(madrugada, "pausado")
                guardar_estado(reloj=RELOJ.como_dict())
                return {"pasos": [marcar(sesion, persona)],
                        "siguiente": "El reloj quedó en las 03:00 (pausado). Vuelve a una comida para seguir."}
            if servicio.comida_id is None or not servicio.vigente:
                raise HTTPException(409, "Fuera de horario: elige una comida en el reloj antes de este caso.")
            derecho = ids_con_derecho(servicio)
            if tipo == "normal":
                uid = sesion.execute(
                    select(Comensal.usuario_id).where(Comensal.usuario_id.in_(derecho))
                    .where(Comensal.usuario_id.not_in(ids_que_comieron(servicio)))
                    .order_by(Comensal.usuario_id).limit(1)
                ).scalar()
                if uid is None:
                    raise HTTPException(409, f"Nadie con derecho pendiente en {servicio.comida} del "
                                             f"{servicio.fecha_comida:%d/%m/%Y}. Ve a una fecha con turnos o limpia.")
                return {"pasos": [marcar(sesion, uid)], "siguiente": "Revisa la pantalla de cocina."}
            if tipo == "duplicado":
                uid = sesion.execute(
                    select(Comensal.usuario_id).where(Comensal.usuario_id.in_(ids_que_comieron(servicio)))
                    .order_by(Comensal.usuario_id).limit(1)
                ).scalar()
                pasos = []
                if uid is None:
                    uid = sesion.execute(
                        select(Comensal.usuario_id).where(Comensal.usuario_id.in_(derecho))
                        .order_by(Comensal.usuario_id).limit(1)
                    ).scalar()
                    if uid is None:
                        raise HTTPException(409, f"Nadie tiene derecho a {servicio.comida} en esta fecha.")
                    pasos.append(marcar(sesion, uid))
                pasos.append(marcar(sesion, uid))
                return {"pasos": pasos, "siguiente": "La segunda lectura debe salir rechazada por duplicado."}
            if tipo == "sin_derecho":
                uid = sesion.execute(
                    select(Comensal.usuario_id).where(Comensal.usuario_id.not_in(derecho))
                    .where(Comensal.tiene_ficha == 1).order_by(Comensal.usuario_id).limit(1)
                ).scalar()
                if uid is None:
                    raise HTTPException(409, "Todo el padrón tiene derecho a esta comida.")
                return {"pasos": [marcar(sesion, uid)], "siguiente": "Debe salir rechazada: sin derecho."}
            raise HTTPException(422, "Caso desconocido")

    @router.get("/api/actividad")
    def actividad(peticion: Request, limite: int = 30):
        """Las lecturas del laboratorio, la más reciente primero, con su resultado final."""
        solo_local(peticion)
        limite = max(1, min(limite, 100))
        with SesionLocal() as sesion:
            filas = sesion.execute(
                select(LecturaBiometrica, Comensal.nombre_completo, Asistencia.id, Asistencia.metodo,
                       Asistencia.usuario_id)
                .outerjoin(Comensal, Comensal.usuario_id == LecturaBiometrica.usuario_id)
                .outerjoin(Asistencia, Asistencia.lectura_id == LecturaBiometrica.id)
                .where(LecturaBiometrica.dispositivo == DISPOSITIVO)
                .order_by(LecturaBiometrica.id.desc()).limit(limite)
            ).all()
            identificados = {
                uid: nombre for uid, nombre in sesion.execute(
                    select(Comensal.usuario_id, Comensal.nombre_completo).where(
                        Comensal.usuario_id.in_(sorted({f[4] for f in filas if f[4] is not None}) or [-1]))
                ).all()
            }
            return [
                {
                    "id": lectura.id,
                    "hora": lectura.fecha_hora.isoformat(timespec="seconds"),
                    "usuario_id": lectura.usuario_id,
                    "nombre": nombre,
                    "resultado": lectura.resultado,
                    "motivo": lectura.motivo,
                    "entrega": None if asistencia_id is None else {
                        "metodo": metodo,
                        "por_cocina": lectura.usuario_id is None,
                        "nombre": identificados.get(entregado_a),
                    },
                }
                for lectura, nombre, asistencia_id, metodo, entregado_a in filas
            ]

    class CuerpoLimpiar(BaseModel):
        confirmar: bool = False

    @router.post("/api/limpiar")
    def limpiar(cuerpo: CuerpoLimpiar, peticion: Request):
        """Borra lo que creó el laboratorio: lecturas, sus entregas y sus intervenciones."""
        solo_local(peticion)
        if not cuerpo.confirmar:
            raise HTTPException(422, "Confirma la limpieza.")
        with SesionLocal() as sesion:
            ids = list(sesion.execute(lecturas_lab()).scalars())
            if not ids:
                return {"lecturas": 0, "entregas": 0, "intervenciones": 0}
            intervenciones = sesion.execute(
                delete(IntervencionLectura).where(IntervencionLectura.lectura_id.in_(ids))
            ).rowcount
            entregas = sesion.execute(delete(Asistencia).where(Asistencia.lectura_id.in_(ids))).rowcount
            lecturas = sesion.execute(delete(LecturaBiometrica).where(LecturaBiometrica.id.in_(ids))).rowcount
            sesion.commit()
            return {"lecturas": lecturas, "entregas": entregas, "intervenciones": intervenciones}

    # --- cuentas ---

    @router.get("/api/cuentas")
    def cuentas(peticion: Request):
        solo_local(peticion)
        ahora = datetime.now()
        with SesionLocal() as sesion:
            filas = sesion.execute(
                select(UsuarioSistema).order_by(UsuarioSistema.rol, UsuarioSistema.username).limit(CUENTAS_LIMITE)
            ).scalars().all()
            return [
                {
                    "usuario": u.username, "rol": u.rol, "activa": bool(u.activo),
                    "debe_cambiar": bool(u.debe_cambiar),
                    "bloqueada_hasta": (lambda h: h.isoformat(timespec="seconds") if h else None)(
                        bloqueado_hasta(sesion, u.username, ahora)),
                }
                for u in filas
            ]

    @router.post("/api/cuentas/{usuario}/clave-temporal")
    def clave_temporal(usuario: str, peticion: Request):
        """Clave temporal nueva y sin bloqueo: el próximo ingreso pide cambiarla."""
        solo_local(peticion)
        from app.semillas.admin import sembrar

        with SesionLocal() as sesion:
            cuenta = sesion.execute(
                select(UsuarioSistema).where(UsuarioSistema.username == usuario)
            ).scalar_one_or_none()
            if cuenta is None:
                raise HTTPException(404, "Esa cuenta no existe.")
            ultimo_exito = sesion.execute(
                select(func.max(IntentoLogin.id)).where(
                    IntentoLogin.username == cuenta.username, IntentoLogin.resultado == "exitoso")
            ).scalar_one()
            fallidos = delete(IntentoLogin).where(
                IntentoLogin.username == cuenta.username,
                IntentoLogin.resultado.in_(("fallido", "bloqueado")),
            )
            if ultimo_exito is not None:
                fallidos = fallidos.where(IntentoLogin.id > ultimo_exito)
            sesion.execute(fallidos)
            sesion.commit()
            rol = cuenta.rol
        clave = sembrar(usuario, rol=rol, resetear=True)
        return {"usuario": usuario, "clave_temporal": clave}

    # Una sola sentencia que demuestra que la conexión funciona, para el arranque.
    def comprobar():
        with SesionLocal() as sesion:
            sesion.execute(text("SELECT 1 FROM v_comensales LIMIT 1")).all()

    router.comprobar = comprobar
    return router


# --- arranque ----------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", choices=sorted(BASES), default="real")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    preparar_entorno(args.base)
    from app.core import reloj as reloj_app

    # Toda la app lee `reloj.ahora()` por atributo del módulo: basta con
    # reemplazarlo acá. `reloj.real()` (tokens, bloqueo) queda intacto.
    reloj_app.ahora = RELOJ.ahora
    RELOJ.restaurar(leer_estado().get("reloj", {}))

    import uvicorn
    from app.main import app

    router = crear_router()
    try:
        router.comprobar()
    except Exception as error:  # noqa: BLE001 - se informa y se sale
        raise SystemExit(f"No se pudo leer la base {os.environ['DB_NAME']}: {error.__class__.__name__}: {error}")
    app.include_router(router)

    propia, turnos = BASES[args.base]
    print("")
    print("  LABORATORIO QA - COMEDOR")
    print(f"  Base propia : {propia}")
    print(f"  Turnos      : {turnos} (solo lectura)")
    print(f"  Reloj       : {RELOJ.modo} {RELOJ.ancla or ''}")
    print(f"  Panel       : http://127.0.0.1:{args.port}/_lab")
    print(f"  API         : http://127.0.0.1:{args.port}")
    print("  Ctrl+C para detener.", flush=True)
    print("", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
