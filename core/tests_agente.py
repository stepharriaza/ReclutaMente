import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.agente_contexto import (
    construir_contexto_agente,
    construir_prompt_agente,
)
from core.models import (
    Categoria,
    Convocatoria,
    Empresa,
    EstadoIntento,
    EstadoTest,
    Intento,
    Persona,
    Plaza,
    Postulacion,
    Test,
    Usuario,
)


class AgenteContextoTest(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create(
            nombre_usuario='empresa_agente',
            email='empresa_agente@example.com',
            contrasena='clave',
            rol='empresa',
        )
        self.empresa = Empresa.objects.create(
            nombre='Empresa Agente',
            usuario=self.usuario,
        )
        self.django_user = User.objects.create_user(
            username=self.usuario.nombre_usuario,
            password='clave',
        )

        self.plaza = Plaza.objects.create(
            nombre='Coordinador de Operaciones',
            descripcion='Coordinar equipos',
            requisitos='Experiencia en operaciones',
            empresa=self.empresa,
        )
        self.categoria = Categoria.objects.create(nombre='Operaciones')
        self.test = Test.objects.create(
            nombre='Prueba de operaciones',
            categoria=self.categoria,
            estado=EstadoTest.PUBLICADO,
        )
        self.plaza.tests.add(self.test)
        self.convocatoria = Convocatoria.objects.create(
            nombre='Convocatoria de operaciones',
            plaza=self.plaza,
        )

        persona_usuario = Usuario.objects.create(
            nombre_usuario='candidato_agente',
            email='candidato_agente@example.com',
            contrasena='clave',
            rol='profesional',
        )
        self.persona = Persona.objects.create(
            nombre='Carla Candidata',
            email='carla@example.com',
            usuario=persona_usuario,
        )
        self.postulacion = Postulacion.objects.create(
            persona=self.persona,
            convocatoria=self.convocatoria,
        )
        self.intento = Intento.objects.create(
            persona=self.persona,
            test=self.test,
            postulacion=self.postulacion,
            estado=EstadoIntento.COMPLETADO,
            puntaje_total=88,
        )
        self.clave_seleccion = f'evaluacion_ia_plaza_{self.plaza.id}'

    def _request(self, usuario=None, ruta='/empresa/dashboard/'):
        request = RequestFactory().get(ruta)
        request.user = usuario or self.django_user
        request.session = {
            self.clave_seleccion: {
                'perfil_objetivo': 'jefe',
                'competencias': ['liderazgo'],
                'otros_criterios': 'Experiencia en campo',
                'sesgo': 'equilibrado',
                'sesgo_detalle': '',
            }
        }
        return request

    def test_contexto_evaluacion_incluye_plaza_participantes_y_criterios(self):
        ruta = reverse(
            'empresa_evaluar_participantes_ia', args=[self.plaza.id]
        )

        contexto = construir_contexto_agente(
            self._request(ruta=ruta),
            ruta_pagina=ruta,
        )

        self.assertEqual(
            contexto['pagina']['url_name'],
            'empresa_evaluar_participantes_ia',
        )
        self.assertEqual(contexto['pagina']['modulo'], 'empresa')
        self.assertEqual(contexto['usuario']['rol'], 'empresa')
        self.assertEqual(
            contexto['datos']['plaza'], 'Coordinador de Operaciones'
        )
        self.assertEqual(contexto['datos']['intentos_completados'], 1)
        self.assertEqual(
            contexto['datos']['total_participantes_completados'], 1
        )
        self.assertEqual(
            contexto['datos']['criterios_guardados']['perfil_objetivo'],
            'jefe',
        )
        self.assertIn('liderazgo', contexto['datos']['criterios_guardados']['competencias'])

    def test_otra_empresa_no_expone_datos_de_la_plaza(self):
        otro_usuario = Usuario.objects.create(
            nombre_usuario='otra_empresa_agente',
            email='otra_agente@example.com',
            contrasena='clave',
            rol='empresa',
        )
        Empresa.objects.create(nombre='Otra Agente', usuario=otro_usuario)
        otro_django_user = User.objects.create_user(
            username=otro_usuario.nombre_usuario,
            password='clave',
        )
        ruta = reverse(
            'empresa_evaluar_participantes_ia', args=[self.plaza.id]
        )

        contexto = construir_contexto_agente(
            self._request(usuario=otro_django_user, ruta=ruta),
            ruta_pagina=ruta,
        )

        self.assertEqual(contexto['pagina']['modulo'], 'empresa')
        self.assertNotIn('plaza', contexto['datos'])
        self.assertNotIn('criterios_guardados', contexto['datos'])

    def test_contexto_profesional_incluye_sus_intentos(self):
        persona_django_user = User.objects.create_user(
            username=self.persona.usuario.nombre_usuario,
            password='clave',
        )
        ruta = reverse('home_profesionales')

        contexto = construir_contexto_agente(
            self._request(
                usuario=persona_django_user,
                ruta=ruta,
            ),
            ruta_pagina=ruta,
        )

        self.assertEqual(contexto['usuario']['rol'], 'profesional')
        self.assertEqual(contexto['datos']['persona'], 'Carla Candidata')
        self.assertEqual(contexto['datos']['intentos_completados'], 1)

    def test_contexto_superadmin_incluye_totales(self):
        superadmin_usuario = Usuario.objects.create(
            nombre_usuario='superadmin_agente',
            email='superadmin_agente@example.com',
            contrasena='clave',
            rol='superadmin',
        )
        superadmin_django_user = User.objects.create_user(
            username=superadmin_usuario.nombre_usuario,
            password='clave',
        )
        ruta = reverse('superadmin_dashboard')

        contexto = construir_contexto_agente(
            self._request(
                usuario=superadmin_django_user,
                ruta=ruta,
            ),
            ruta_pagina=ruta,
        )

        self.assertEqual(contexto['usuario']['rol'], 'superadmin')
        self.assertGreaterEqual(contexto['datos']['total_empresas'], 1)
        self.assertGreaterEqual(contexto['datos']['total_intentos'], 1)

    def test_ruta_invalida_cae_en_contexto_publico(self):
        contexto = construir_contexto_agente(
            self._request(ruta='/ruta-que-no-existe/'),
            ruta_pagina='/ruta-que-no-existe/',
        )

        self.assertEqual(contexto['pagina']['url_name'], '')
        self.assertEqual(contexto['pagina']['modulo'], 'publico')
        self.assertEqual(contexto['datos'], {})

    def test_prompt_incluye_pagina_datos_reglas_e_historial(self):
        ruta = reverse(
            'empresa_evaluar_participantes_ia', args=[self.plaza.id]
        )
        contexto = construir_contexto_agente(
            self._request(ruta=ruta),
            ruta_pagina=ruta,
            historial=[
                {'rol': 'usuario', 'contenido': '¿Por qué no puedo evaluar?'},
                {'rol': 'agente', 'contenido': 'Revisemos los participantes.'},
            ],
        )

        prompt = construir_prompt_agente(
            '¿Qué hago en esta pantalla?', contexto
        )

        self.assertIn('Coordinador de Operaciones', prompt)
        self.assertIn('empresa_evaluar_participantes_ia', prompt)
        self.assertIn('No preguntes al usuario qué pantalla', prompt)
        self.assertIn('Revisemos los participantes.', prompt)
        self.assertIn('¿Qué hago en esta pantalla?', prompt)

    def test_historial_se_limita_y_normaliza(self):
        historial = [
            {'rol': 'usuario', 'contenido': f'Mensaje {indice}'}
            for indice in range(20)
        ]
        historial.append({'rol': 'otro', 'contenido': 'Mensaje final'})
        historial.append({'rol': 'usuario', 'contenido': '   '})

        contexto = construir_contexto_agente(
            self._request(),
            ruta_pagina='/empresa/dashboard/',
            historial=historial,
        )

        self.assertEqual(len(contexto['historial']), 12)
        self.assertEqual(contexto['historial'][-1]['rol'], 'usuario')
        self.assertEqual(
            contexto['historial'][-1]['contenido'], 'Mensaje final'
        )


class ApiAgenteContextoTest(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create(
            nombre_usuario='empresa_api_agente',
            email='empresa_api_agente@example.com',
            contrasena='clave',
            rol='empresa',
        )
        self.empresa = Empresa.objects.create(
            nombre='Empresa API Agente',
            usuario=self.usuario,
        )
        self.django_user = User.objects.create_user(
            username=self.usuario.nombre_usuario,
            password='clave',
        )
        self.client.force_login(self.django_user)
        self.plaza = Plaza.objects.create(
            nombre='Jefatura de Servicio',
            empresa=self.empresa,
        )
        self.url = reverse('api_agente_ia')

    def _post(self, datos):
        return self.client.post(
            self.url,
            data=json.dumps(datos),
            content_type='application/json',
        )

    @patch('Reclutamente.views.generar_contenido_seguro')
    def test_endpoint_envia_contexto_de_pagina_al_prompt(self, generar_mock):
        generar_mock.return_value = 'Debes invitar primero a los participantes.'
        ruta = reverse(
            'empresa_invitar_participantes', args=[self.plaza.id]
        )

        response = self._post(
            {
                'mensaje': '¿Cómo invito a alguien?',
                'historial': [
                    {'rol': 'usuario', 'contenido': 'Hola'},
                    {'rol': 'agente', 'contenido': '¿En qué te ayudo?'},
                ],
                'contexto_pagina': {'ruta': ruta, 'titulo': 'Participantes'},
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['respuesta'],
            'Debes invitar primero a los participantes.',
        )
        prompt = generar_mock.call_args.args[0]
        self.assertIn('Jefatura de Servicio', prompt)
        self.assertIn('empresa_invitar_participantes', prompt)
        self.assertIn('No preguntes al usuario qué pantalla', prompt)
        self.assertIn('¿Cómo invito a alguien?', prompt)
        self.assertIn('¿En qué te ayudo?', prompt)

    @patch('Reclutamente.views.generar_contenido_seguro')
    def test_endpoint_usa_referer_si_no_llega_contexto(self, generar_mock):
        generar_mock.return_value = 'Respuesta.'

        response = self.client.post(
            self.url,
            data=json.dumps({'mensaje': 'Ayuda'}),
            content_type='application/json',
            HTTP_REFERER=f'http://testserver{reverse("empresa_dashboard")}',
        )

        self.assertEqual(response.status_code, 200)
        prompt = generar_mock.call_args.args[0]
        self.assertIn('empresa_dashboard', prompt)

    def test_endpoint_rechaza_mensaje_vacio(self):
        response = self._post({'mensaje': '   '})

        self.assertEqual(response.status_code, 400)

    def test_endpoint_rechaza_mensaje_demasiado_largo(self):
        response = self._post({'mensaje': 'x' * 2001})

        self.assertEqual(response.status_code, 400)

    def test_endpoint_rechaza_json_invalido(self):
        response = self.client.post(
            self.url,
            data='{no-es-json',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)

    @patch('Reclutamente.views.generar_contenido_seguro')
    def test_base_renderiza_contexto_del_agente(self, generar_mock):
        response = self.client.get(reverse('empresa_dashboard'))

        self.assertContains(response, 'RECLUTA_AGENTE_CONTEXTO')
        self.assertContains(response, 'reclutamente_agente_historial_v1')
