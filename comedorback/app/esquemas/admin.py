"""Formas de la administración de cuentas. CONTRATO con el front: no cambiar sin avisar."""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class CuentaAdmin(BaseModel):
    """Una cuenta del comedor tal como la ve root."""

    id: int
    username: str
    rol: str = Field(description="jefa | cocinera | sistemas")
    activo: bool
    debe_cambiar: bool = Field(description="True = clave temporal, pendiente de cambio")
    usuario_turnos_id: int | None = Field(description="users.id vinculado, o null si es sin vínculo")
    vinculada: bool = Field(description="True si nació desde el padrón")
    nombre: str | None = Field(
        description="De v_comensales si está vinculada; si no, el nombre a mano"
    )
    categoria: str | None = Field(description="De v_comensales si está vinculada")
    creada: datetime
    ultimo_ingreso: datetime | None = Field(
        description="Último intento exitoso, o null si nunca ingresó"
    )


class Candidato(BaseModel):
    """Una persona del padrón, con o sin cuenta todavía."""

    usuario_turnos_id: int = Field(description="users.id")
    login: str | None = Field(description="users.name, tal como figura en el padrón")
    nombre: str | None = Field(description="Nombre completo, o null si no tiene ficha")
    categoria: str | None
    cuenta_id: int | None = Field(description="La cuenta que ya tiene, o null")


class CrearCuenta(BaseModel):
    """Una de dos formas: vinculada {rol, usuario_turnos_id} o sin vínculo
    {rol, username, nombre}. El rol se valida en la lógica, para responder
    con motivo (rol_no_permitido) en vez del 422 genérico."""

    rol: str = Field(description="cocinera | jefa (sistemas solo por consola)")
    usuario_turnos_id: int | None = Field(default=None, gt=0)
    username: str | None = Field(default=None, min_length=1, max_length=50)
    nombre: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def una_sola_forma(self):
        vinculada = self.usuario_turnos_id is not None
        a_mano = self.username is not None or self.nombre is not None
        if vinculada and a_mano:
            raise ValueError("O se vincula al padrón o se da username y nombre, no ambos.")
        if vinculada:
            return self
        if self.username is None or self.nombre is None:
            raise ValueError("Sin vínculo hay que dar username y nombre.")
        username = self.username.strip()
        nombre = self.nombre.strip()
        if not username or not nombre:
            raise ValueError("El username y el nombre no pueden estar vacíos.")
        self.username = username
        self.nombre = nombre
        return self


class CuentaConClave(BaseModel):
    """201 de creación y 200 de reinicio: la cuenta y su clave temporal, que
    se muestra una sola vez y nunca se registra en logs."""

    cuenta: CuentaAdmin
    clave_temporal: str
