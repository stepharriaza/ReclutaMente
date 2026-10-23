from decimal import Decimal
from django.db import models
from django.utils import timezone


class Ticket(models.Model):
    ESTADOS = (
        ('Abierto', 'Abierto'),
        ('En proceso', 'En proceso'),
        ('Resuelto', 'Resuelto'),
    )
    
    empresa = models.ForeignKey('Empresa', on_delete=models.CASCADE, related_name="tickets")
    asunto = models.CharField(max_length=200)
    mensaje = models.TextField()
    estado = models.CharField(max_length=20, choices=ESTADOS, default='Abierto')
    respuesta_admin = models.TextField(blank=True, null=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Ticket #{self.id} - {self.asunto}"

class Plaza(models.Model):
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    requisitos = models.TextField(blank=True)
    ubicacion = models.CharField(max_length=150, blank=True, null=True)
    modalidad = models.CharField(max_length=50, blank=True, null=True)
    fecha_limite = models.DateField(blank=True, null=True)
    empresa = models.ForeignKey('Empresa', on_delete=models.CASCADE, related_name="plazas")

    def __str__(self):
        return self.nombre

    @property
    def esta_vencida(self):
        if self.fecha_limite:
            return self.fecha_limite < timezone.now().date()
        return False

class Bitacora(models.Model):
    fecha_hora = models.DateTimeField(auto_now_add=True)
    usuario = models.CharField(max_length=150)
    accion = models.CharField(max_length=255)
    modulo = models.CharField(max_length=150)

    def __str__(self):
        return f"{self.usuario} - {self.accion} ({self.fecha_hora})"

class Ticket(models.Model):
    TIPO_TICKET = (
        ('Soporte General', 'Soporte General'),
        ('Modificación de Prueba', 'Modificación de Prueba'),
        ('Chequeo de Plataforma', 'Chequeo de Plataforma'),
        ('Chequeo de Agente', 'Chequeo de Agente'),
    )

    DESTINO_MODIFICACION = (
        ('Sistema', 'Sistema'),
        ('Agente', 'Agente'),
        ('Plataforma General', 'Plataforma General'),
        ('N/A', 'No aplica'),
    )

    ESTADOS = (
        ('Abierto', 'Abierto'),
        ('En proceso', 'En proceso'),
        ('Resuelto', 'Resuelto'),
    )

    codigo = models.CharField(max_length=50, unique=True, blank=True, null=True)
    empresa = models.ForeignKey('Empresa', on_delete=models.CASCADE, related_name="tickets", blank=True, null=True)
    tipo = models.CharField(max_length=50, choices=TIPO_TICKET, default='Soporte General')
    asunto = models.CharField(max_length=200, blank=True, null=True)
    prueba = models.CharField(max_length=150, blank=True, null=True)
    destino = models.CharField(max_length=50, choices=DESTINO_MODIFICACION, default='N/A')
    rango_fechas = models.CharField(max_length=100, blank=True, null=True)
    descripcion = models.TextField(blank=True, null=True)
    estado = models.CharField(max_length=50, choices=ESTADOS, default='Abierto')
    respuesta_admin = models.TextField(blank=True, null=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Ticket #{self.codigo or self.id} - [{self.tipo}] {self.asunto or self.prueba}"


class EstadoTest(models.TextChoices):
    BORRADOR = "borrador", "Borrador"
    PUBLICADO = "publicado", "Publicado"
    DESACTIVADO = "desactivado", "Desactivado"


class EstadoConvocatoria(models.TextChoices):
    BORRADOR = "borrador", "Borrador"
    ABIERTA = "abierta", "Abierta"
    EN_EVALUACION = "en_evaluacion", "En evaluacion"
    CERRADA = "cerrada", "Cerrada"


class EstadoPostulacion(models.TextChoices):
    EN_PROCESO = "en_proceso", "En proceso"
    COMPLETADO = "completado", "Completado"
    SELECCIONADO = "seleccionado", "Seleccionado"
    RECHAZADO = "rechazado", "Rechazado"


class EstadoIntento(models.TextChoices):
    INICIADO = "iniciado", "Iniciado"
    EN_PROGRESO = "en_progreso", "En progreso"
    COMPLETADO = "completado", "Completado"


class Usuario(models.Model):
    ROL_CHOICES = (
        ('profesional', 'Profesional'),
        ('empresa', 'Empresa'),
        ('superadmin', 'Superadmin'),
    )

    nombre_usuario = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    contrasena = models.CharField(max_length=255)
    rol = models.CharField(max_length=20, choices=ROL_CHOICES, null=True, blank=True)

    def __str__(self):
        return self.nombre_usuario
    
    class Meta:
        db_table = 'core_usuario'


class Persona(models.Model):
    nombre = models.CharField(max_length=200)
    email = models.EmailField()
    telefono = models.CharField(max_length=20, blank=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)

    def __str__(self):
        return self.nombre


class Empresa(models.Model):
    nombre = models.CharField(max_length=200)
    plan = models.CharField(max_length=50, blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    estado = models.CharField(max_length=20, default='Activa') # <--- Agrege esta línea Katty

    def __str__(self):
        return self.nombre


class Categoria(models.Model):
    id = models.AutoField(primary_key=True, db_column="id_categoria")
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)

    class Meta:
        db_table = "categoria"

    def __str__(self):
        return self.nombre


class Test(models.Model):
    id = models.AutoField(primary_key=True, db_column="id_test")
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    duracion_estimada = models.PositiveIntegerField(blank=True, null=True)
    version = models.CharField(max_length=20, blank=True)
    estado = models.CharField(max_length=20, choices=EstadoTest.choices, default=EstadoTest.BORRADOR)
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, db_column="id_categoria")

    class Meta:
        db_table = "test"

    def __str__(self):
        return self.nombre


class Pregunta(models.Model):
    id = models.AutoField(primary_key=True, db_column="id_pregunta")
    texto_pregunta = models.TextField()
    dimension = models.CharField(max_length=100, blank=True)
    fila = models.PositiveIntegerField(null=True, blank=True)
    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="preguntas", db_column="id_test")

    class Meta:
        db_table = "pregunta"

    def __str__(self):
        return self.texto_pregunta[:50]


class Convocatoria(models.Model):
    nombre = models.CharField(max_length=200)
    estado = models.CharField(
        max_length=30, choices=EstadoConvocatoria.choices, default=EstadoConvocatoria.BORRADOR
    )
    requisito = models.TextField(blank=True)
    invitacion = models.CharField(max_length=255, blank=True)
    plaza = models.ForeignKey(Plaza, on_delete=models.CASCADE, related_name="convocatorias")

    def __str__(self):
        return self.nombre


class Postulacion(models.Model):
    fecha = models.DateField(auto_now_add=True)
    estado = models.CharField(
        max_length=30, choices=EstadoPostulacion.choices, default=EstadoPostulacion.EN_PROCESO
    )
    datos = models.TextField(blank=True)
    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="postulaciones")
    convocatoria = models.ForeignKey(Convocatoria, on_delete=models.CASCADE, related_name="postulaciones")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["persona", "convocatoria"], name="uniq_persona_convocatoria")
        ]

    def __str__(self):
        return f"{self.persona} - {self.convocatoria}"


class Intento(models.Model):
    estado = models.CharField(max_length=30, choices=EstadoIntento.choices, default=EstadoIntento.INICIADO)
    fecha = models.DateField(auto_now_add=True)
    duracion_minutos = models.PositiveIntegerField(blank=True, null=True)
    puntaje_total = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    puntaje_dimensiones = models.TextField(blank=True)
    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="intentos")
    test = models.ForeignKey(Test, on_delete=models.PROTECT, related_name="intentos")
    postulacion = models.ForeignKey(Postulacion, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.persona} - {self.test}"


class Respuesta(models.Model):
    texto_respuesta = models.TextField(blank=True)
    tipo = models.CharField(max_length=30, blank=True)
    dimension = models.CharField(max_length=100, blank=True)
    intento = models.ForeignKey(Intento, on_delete=models.CASCADE, related_name="respuestas")
    pregunta = models.ForeignKey(Pregunta, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["intento", "pregunta"], name="uniq_intento_pregunta")
        ]

    def __str__(self):
        return f"{self.intento} - {self.pregunta}"


class AnalisisIA(models.Model):
    intento = models.OneToOneField(Intento, on_delete=models.CASCADE, related_name="analisis_ia")
    perfil = models.JSONField(blank=True, null=True)
    informe_texto = models.TextField(blank=True)
    modelo_usado = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"Analisis de {self.intento}"


class Certificado(models.Model):
    codigo_verificacion = models.CharField(max_length=100, unique=True)
    fecha_emision = models.DateField(auto_now_add=True)
    pdf = models.CharField(max_length=500, blank=True)
    intento = models.OneToOneField(Intento, on_delete=models.CASCADE, related_name="certificado")

    def __str__(self):
        return self.codigo_verificacion


class PruebaGeneradaEmpresa(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name="pruebas_ia")
    puesto = models.CharField(max_length=200)
    criterios_requeridos = models.TextField(help_text="Ej: Liderazgo, analítico, estadísticas")
    contenido_prueba = models.TextField(help_text="Contenido de la prueba redactado por la IA")
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Prueba para {self.puesto} - {self.empresa.nombre}"
