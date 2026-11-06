from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import (
    Categoria,
    Certificado,
    EstadoIntento,
    EstadoTest,
    Intento,
    Persona,
    Pregunta,
    Test,
    Usuario,
)
from core.services import (
    generar_pdf_certificado,
    resultado_temperamento_respaldo,
)


class ResultadoTemperamentoTest(SimpleTestCase):
    def test_identifica_predominante_secundario_y_puntajes(self):
        resultado = resultado_temperamento_respaldo(
            {'C': 39, 'S': 37, 'F': 23, 'M': 21}
        )

        self.assertEqual(resultado['temperamento_predominante'], 'Colérico')
        self.assertEqual(resultado['temperamento_secundario'], 'Sanguíneo')
        self.assertFalse(resultado['perfil_combinado'])
        self.assertEqual(resultado['fuente'], 'local')
        self.assertEqual(len(resultado['dimensiones']), 4)
        self.assertEqual(resultado['dimensiones'][0]['puntaje'], 39)
        self.assertEqual(resultado['dimensiones'][0]['maximo'], 48)
        self.assertTrue(resultado['fortalezas'])
        self.assertTrue(resultado['areas_desarrollo'])

    def test_reconoce_un_empate_como_perfil_combinado(self):
        resultado = resultado_temperamento_respaldo(
            {'C': 30, 'S': 30, 'F': 30, 'M': 30}
        )

        self.assertTrue(resultado['perfil_combinado'])
        self.assertEqual(resultado['temperamento_secundario'], '')
        self.assertIn('Colérico', resultado['temperamento_predominante'])
        self.assertIn('Sanguíneo', resultado['temperamento_predominante'])

    def test_pdf_contiene_documento_valido_con_datos_en_espanol(self):
        resultados = resultado_temperamento_respaldo(
            {'C': 39, 'S': 37, 'F': 23, 'M': 21}
        )
        certificado = SimpleNamespace(
            codigo_verificacion='RM-TEM-PRUEBA123',
            fecha_emision=date(2026, 11, 5),
            resultados=resultados,
            analisis=resultados['resumen'],
            intento=SimpleNamespace(
                persona=SimpleNamespace(nombre='María José Pérez'),
                test=SimpleNamespace(nombre='Test de Temperamentos'),
            ),
        )

        contenido = generar_pdf_certificado(certificado)

        self.assertTrue(contenido.startswith(b'%PDF-'))
        self.assertGreater(len(contenido), 2000)


class CertificacionTemperamentoFlowTest(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create(
            nombre_usuario='profesional_temperamento',
            email='temperamento@example.com',
            contrasena='clave',
            rol='profesional',
        )
        self.persona = Persona.objects.create(
            nombre='Ana García',
            email=self.usuario.email,
            usuario=self.usuario,
        )
        self.django_user = User.objects.create_user(
            username=self.usuario.nombre_usuario,
            password='clave',
        )
        self.client.force_login(self.django_user)

        self.categoria = Categoria.objects.create(nombre='Personalidad')
        self.test = Test.objects.create(
            nombre='Test de Temperamentos',
            categoria=self.categoria,
            estado=EstadoTest.PUBLICADO,
        )
        self.preguntas = {}
        for clave, texto in (
            ('C', 'Decidido'),
            ('S', 'Entusiasta'),
            ('F', 'Calmado'),
            ('M', 'Analítico'),
        ):
            self.preguntas[clave] = Pregunta.objects.create(
                texto_pregunta=texto,
                dimension=clave,
                fila=1,
                test=self.test,
            )
        self.intento = Intento.objects.create(
            persona=self.persona,
            test=self.test,
            estado=EstadoIntento.INICIADO,
        )
        self.url = reverse('resolver_test', args=[self.intento.id])
        self.respuestas = {
            f'valor_{self.preguntas["C"].id}': '4',
            f'valor_{self.preguntas["S"].id}': '3',
            f'valor_{self.preguntas["F"].id}': '2',
            f'valor_{self.preguntas["M"].id}': '1',
        }

    def test_finalizar_genera_analisis_certificacion_y_pdf(self):
        resultado_ia = resultado_temperamento_respaldo(
            {'C': 4, 'S': 3, 'F': 2, 'M': 1}
        )
        resultado_ia['fuente'] = 'ia'
        resultado_ia['modelo'] = 'gemini-prueba'

        with patch(
            'Reclutamente.views.analizar_temperamento',
            return_value=resultado_ia,
        ) as analizar_mock:
            response = self.client.post(self.url, self.respuestas)

        self.assertRedirects(
            response,
            reverse('profesional_certificaciones'),
            fetch_redirect_response=False,
        )
        analizar_mock.assert_called_once()
        self.intento.refresh_from_db()
        self.assertEqual(self.intento.estado, EstadoIntento.COMPLETADO)

        certificado = Certificado.objects.get(intento=self.intento)
        self.assertEqual(certificado.resultados['fuente'], 'ia')
        self.assertEqual(certificado.modelo_usado, 'gemini-prueba')
        self.assertEqual(
            certificado.resultados['temperamento_predominante'], 'Colérico'
        )
        self.assertTrue(certificado.pdf)
        self.assertFalse(hasattr(self.intento, 'analisis_ia'))

        pagina = self.client.get(reverse('profesional_certificaciones'))
        self.assertContains(pagina, 'Colérico')
        self.assertContains(pagina, 'Resultados por dimensión')
        self.assertContains(pagina, 'Descargar PDF')

        descarga = self.client.get(
            reverse('descargar_certificado', args=[certificado.id])
        )
        self.assertEqual(descarga.status_code, 200)
        self.assertEqual(descarga['Content-Type'], 'application/pdf')
        self.assertIn('attachment', descarga['Content-Disposition'])
        self.assertTrue(descarga.content.startswith(b'%PDF-'))

    def test_usa_respaldo_si_el_agente_no_esta_disponible(self):
        with patch(
            'Reclutamente.views.analizar_temperamento',
            side_effect=Exception('IA no disponible'),
        ):
            response = self.client.post(self.url, self.respuestas)

        self.assertEqual(response.status_code, 302)
        certificado = Certificado.objects.get(intento=self.intento)
        self.assertEqual(certificado.resultados['fuente'], 'local')
        self.assertEqual(certificado.modelo_usado, 'Guía de interpretación ReclutaMente')

    def test_no_permite_descargar_certificado_de_otra_persona(self):
        resultado_ia = resultado_temperamento_respaldo(
            {'C': 4, 'S': 3, 'F': 2, 'M': 1}
        )
        with patch(
            'Reclutamente.views.analizar_temperamento', return_value=resultado_ia
        ):
            self.client.post(self.url, self.respuestas)
        certificado = Certificado.objects.get(intento=self.intento)

        otro_usuario = Usuario.objects.create(
            nombre_usuario='otro_profesional',
            email='otro@example.com',
            contrasena='clave',
            rol='profesional',
        )
        Persona.objects.create(
            nombre='Otra Persona', email=otro_usuario.email, usuario=otro_usuario
        )
        otro_django_user = User.objects.create_user(
            username=otro_usuario.nombre_usuario, password='clave'
        )
        self.client.force_login(otro_django_user)

        response = self.client.get(
            reverse('descargar_certificado', args=[certificado.id])
        )

        self.assertEqual(response.status_code, 404)
