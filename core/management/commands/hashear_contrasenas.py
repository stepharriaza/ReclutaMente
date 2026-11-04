"""Convierte contraseñas antiguas en texto plano a hashes de Django."""

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand

from core.auth_utils import es_contrasena_hasheada
from core.models import Usuario


class Command(BaseCommand):
    help = 'Hashea las contraseñas de Usuario que todavía estén en texto plano.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Muestra cuántas contraseñas se cambiarían sin guardar cambios.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        actualizados = 0
        revisados = 0

        for usuario in Usuario.objects.all().iterator():
            revisados += 1
            valor = usuario.contrasena or ''
            if not valor or es_contrasena_hasheada(valor):
                continue

            if dry_run:
                self.stdout.write(
                    f'[dry-run] Se hashearía la contraseña de '
                    f'{usuario.nombre_usuario}'
                )
            else:
                usuario.contrasena = make_password(valor)
                usuario.save(update_fields=['contrasena'])
            actualizados += 1

        etiqueta = 'se hashearían' if dry_run else 'se hashearon'
        self.stdout.write(
            self.style.SUCCESS(
                f'{revisados} cuenta(s) revisada(s); '
                f'{actualizados} contraseña(s) {etiqueta}.'
            )
        )
