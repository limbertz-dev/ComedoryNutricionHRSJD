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
    """Una de dos formas: vinculada {rol, usuario_turnos_id, password} o sin
    vínculo {rol, username, nombre, password}. El rol y la política de la
    contraseña se validan en la lógica, para responder con motivo
    (rol_no_permitido, password_rechazada) en vez del 422 genérico."""

    rol: str = Field(description="cocinera | jefa (sistemas solo por consola)")
    password: str = Field(
        min_length=1,
        max_length=200,
        description="Contraseña definitiva que elige root: la cuenta entra con ella sin cambio obligatorio",
    )
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


class CuentaRespuesta(BaseModel):
    """201 de creación y 200 de cambio de clave. La contraseña nunca vuelve."""

    cuenta: CuentaAdmin


class NuevaClave(BaseModel):
    """La contraseña que root fija para una cuenta existente."""

    password: str = Field(min_length=1, max_length=200)


class ActualizarCuenta(BaseModel):
    """Datos editables; el usuario de acceso y el historial se conservan."""

    model_config = {"extra": "forbid"}
    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    rol: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validar_cambios(self):
        if not self.model_fields_set:
            raise ValueError("Indique al menos un dato para editar.")
        for campo in self.model_fields_set:
            valor = getattr(self, campo)
            if valor is None or not valor.strip():
                raise ValueError("Los datos editados no pueden estar vacíos.")
            setattr(self, campo, valor.strip())
        return self
