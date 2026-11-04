from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from core.auth_utils import (
    codificar_uid,
    es_contrasena_hasheada,
    generar_token_recuperacion,
)
from core.models import Empresa, Persona, Usuario


PASSWORD_FUERTE = 'FuerzaTotal#9284'
PASSWORD_NUEVA = 'NuevaClaveSegura#2026'


@override_settings(
    MAILERS={
        'default': {
            'BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
        }
    }
)
class AutenticacionTest(TestCase):
    def setUp(self):
        self.password = 'ClaveOriginal2026!'
        self.usuario = Usuario.objects.create(
            nombre_usuario='profesional_auth',
            email='profesional_auth@example.com',
            contrasena=self.password,
            rol='profesional',
        )
        self.persona = Persona.objects.create(
            nombre='Profesional Auth',
            email=self.usuario.email,
            usuario=self.usuario,
        )
        self.django_user = User.objects.create_user(
            username=self.usuario.nombre_usuario,
            email=self.usuario.email,
            password=self.password,
        )

    def _url_confirmacion(self, usuario=None):
        usuario = usuario or self.usuario
        return reverse(
            'password_reset_confirm',
            args=[
                codificar_uid(usuario),
                generar_token_recuperacion(usuario),
            ],
        )

    def test_registro_guarda_hash_y_sincroniza_usuario_django(self):
        response = self.client.post(
            reverse('registro'),
            {
                'username': 'nuevo_profesional',
                'nombre': 'Nuevo Profesional',
                'email': 'nuevo_profesional@example.com',
                'password': PASSWORD_FUERTE,
            },
        )

        self.assertEqual(response.status_code, 302)
        usuario = Usuario.objects.get(nombre_usuario='nuevo_profesional')
        self.assertNotEqual(usuario.contrasena, PASSWORD_FUERTE)
        self.assertTrue(es_contrasena_hasheada(usuario.contrasena))
        self.assertTrue(check_password(PASSWORD_FUERTE, usuario.contrasena))

        django_user = User.objects.get(username='nuevo_profesional')
        self.assertTrue(django_user.check_password(PASSWORD_FUERTE))

    def test_registro_rechaza_contrasena_debil(self):
        response = self.client.post(
            reverse('registro'),
            {
                'username': 'usuario_debil',
                'nombre': 'Usuario Débil',
                'email': 'debil@example.com',
                'password': '123',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            Usuario.objects.filter(nombre_usuario='usuario_debil').exists()
        )

    def test_login_legacy_funciona_y_actualiza_a_hash(self):
        User.objects.filter(username=self.usuario.nombre_usuario).delete()

        response = self.client.post(
            reverse('login'),
            {
                'username': self.usuario.nombre_usuario,
                'password': self.password,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.usuario.refresh_from_db()
        self.assertTrue(es_contrasena_hasheada(self.usuario.contrasena))
        self.assertTrue(check_password(self.password, self.usuario.contrasena))
        django_user = User.objects.get(username=self.usuario.nombre_usuario)
        self.assertTrue(django_user.check_password(self.password))

    def test_login_con_hash_existente_funciona(self):
        self.usuario.contrasena = make_password(self.password)
        self.usuario.save(update_fields=['contrasena'])

        response = self.client.post(
            reverse('login'),
            {
                'username': self.usuario.nombre_usuario,
                'password': self.password,
            },
        )

        self.assertEqual(response.status_code, 302)

    def test_login_muestra_enlace_de_recuperacion(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('password_reset'))
        self.assertContains(response, '¿Olvidaste tu contraseña?')

    def test_login_rechaza_contrasena_incorrecta(self):
        response = self.client.post(
            reverse('login'),
            {
                'username': self.usuario.nombre_usuario,
                'password': 'NoEsLaCorrecta#1',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Usuario o contraseña incorrectos')

    def test_solicitud_de_recuperacion_envia_correo(self):
        respuesta = self.client.post(
            reverse('password_reset'),
            {'email': self.usuario.email},
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('password-reset', mail.outbox[0].body)
        self.assertIn(self.usuario.email, mail.outbox[0].to)

    def test_solicitud_de_correo_inexistente_no_revela_ni_envia(self):
        respuesta = self.client.post(
            reverse('password_reset'),
            {'email': 'no-existe@example.com'},
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    def test_solicitud_de_cuenta_inactiva_no_envia(self):
        self.usuario.activo = False
        self.usuario.save(update_fields=['activo'])

        respuesta = self.client.post(
            reverse('password_reset'),
            {'email': self.usuario.email},
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    def test_enlace_de_recuperacion_permite_cambiar_contrasena(self):
        url = self._url_confirmacion()

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['validlink'])

        response = self.client.post(
            url,
            {
                'password': PASSWORD_NUEVA,
                'password_confirm': PASSWORD_NUEVA,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.usuario.refresh_from_db()
        self.assertTrue(check_password(PASSWORD_NUEVA, self.usuario.contrasena))
        django_user = User.objects.get(username=self.usuario.nombre_usuario)
        self.assertTrue(django_user.check_password(PASSWORD_NUEVA))

    def test_enlace_queda_invalido_despues_de_usarse(self):
        url = self._url_confirmacion()
        self.client.post(
            url,
            {
                'password': PASSWORD_NUEVA,
                'password_confirm': PASSWORD_NUEVA,
            },
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['validlink'])
        self.assertContains(response, 'Enlace inválido o vencido')

    def test_enlace_vencido_es_rechazado(self):
        with self.settings(PASSWORD_RESET_TIMEOUT=-1):
            url = self._url_confirmacion()
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['validlink'])

    def test_contrasenas_que_no_coinciden_no_cambian_la_cuenta(self):
        url = self._url_confirmacion()
        contrasena_original = self.usuario.contrasena

        response = self.client.post(
            url,
            {
                'password': PASSWORD_NUEVA,
                'password_confirm': 'OtraClave#2026',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.contrasena, contrasena_original)
        self.assertTrue(response.context['errores'])

    def test_contrasena_debil_no_se_acepta_en_recuperacion(self):
        url = self._url_confirmacion()
        contrasena_original = self.usuario.contrasena

        response = self.client.post(
            url,
            {
                'password': '123',
                'password_confirm': '123',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.contrasena, contrasena_original)
        self.assertTrue(response.context['errores'])

    def test_perfil_profesional_cambia_contrasena_con_hash(self):
        self.client.force_login(self.django_user)

        response = self.client.post(
            reverse('profesional_perfil'),
            {
                'nombre': self.persona.nombre,
                'email': self.persona.email,
                'telefono': '',
                'contrasena_actual': self.password,
                'contrasena_nueva': PASSWORD_NUEVA,
                'contrasena_confirmar': PASSWORD_NUEVA,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.usuario.refresh_from_db()
        self.assertTrue(check_password(PASSWORD_NUEVA, self.usuario.contrasena))
        self.django_user.refresh_from_db()
        self.assertTrue(self.django_user.check_password(PASSWORD_NUEVA))


    def test_superadmin_crea_empresa_con_contrasena_hasheada(self):
        superadmin = Usuario.objects.create(
            nombre_usuario='superadmin_auth',
            email='superadmin_auth@example.com',
            contrasena=make_password('SuperAdmin#2026'),
            rol='superadmin',
        )
        superadmin_django = User.objects.create_user(
            username=superadmin.nombre_usuario,
            email=superadmin.email,
            password='SuperAdmin#2026',
        )
        self.client.force_login(superadmin_django)

        response = self.client.post(
            reverse('superadmin_empresas'),
            {
                'nombre': 'Empresa Nueva',
                'plan': 'Premium',
                'telefono': '5555-5555',
                'nombre_usuario': 'empresa_nueva',
                'email_admin': 'empresa_nueva@example.com',
                'contrasena_admin': PASSWORD_NUEVA,
            },
        )

        self.assertEqual(response.status_code, 302)
        usuario = Usuario.objects.get(nombre_usuario='empresa_nueva')
        self.assertTrue(es_contrasena_hasheada(usuario.contrasena))
        self.assertTrue(check_password(PASSWORD_NUEVA, usuario.contrasena))
        self.assertTrue(
            Empresa.objects.filter(nombre='Empresa Nueva').exists()
        )
        django_user = User.objects.get(username='empresa_nueva')
        self.assertTrue(django_user.check_password(PASSWORD_NUEVA))


class HashearContrasenasCommandTest(TestCase):
    def test_comando_hashea_contrasenas_en_texto_plano(self):
        usuario = Usuario.objects.create(
            nombre_usuario='usuario_comando',
            email='usuario_comando@example.com',
            contrasena='TextoPlano#2026',
            rol='profesional',
        )

        call_command('hashear_contrasenas')

        usuario.refresh_from_db()
        self.assertTrue(es_contrasena_hasheada(usuario.contrasena))
        self.assertTrue(check_password('TextoPlano#2026', usuario.contrasena))
