import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    AnalisisIA,
    Categoria,
    Convocatoria,
    Empresa,
    EstadoIntento,
    EstadoTest,
    Intento,
    Persona,
    Plaza,
    Postulacion,
    Pregunta,
    Respuesta,
    Test,
    Usuario,
)


class EmpresaEvaluarParticipantesIATest(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create(
            nombre_usuario='empresa_ia',
            email='empresa_ia@example.com',
            contrasena='clave',
            rol='empresa',
        )
        self.empresa = Empresa.objects.create(
            nombre='Empresa IA',
            usuario=self.usuario,
        )
        self.django_user = User.objects.create_user(
            username=self.usuario.nombre_usuario,
            password='clave',
        )
        self.client.force_login(self.django_user)

        self.plaza = Plaza.objects.create(
            nombre='Gerente de Ventas',
            descripcion='Liderazgo comercial',
            requisitos='Experiencia en ventas y liderazgo',
            empresa=self.empresa,
        )
        self.categoria = Categoria.objects.create(nombre='Ventas')
        self.test = Test.objects.create(
            nombre='Perfil comercial',
            categoria=self.categoria,
            estado=EstadoTest.PUBLICADO,
        )
        self.plaza.tests.add(self.test)
        self.convocatoria = Convocatoria.objects.create(
            nombre='Evaluación - Gerente de Ventas',
            plaza=self.plaza,
        )
        self.persona = self._crear_persona(
            'Ana Pérez',
            'ana@example.com',
            'ana',
        )
        self.postulacion = Postulacion.objects.create(
            persona=self.persona,
            convocatoria=self.convocatoria,
        )
        self.pregunta = Pregunta.objects.create(
            texto_pregunta='¿Cómo manejas un equipo?',
            dimension='Liderazgo',
            test=self.test,
        )
        self.intento = self._crear_intento(
            self.persona,
            self.postulacion,
            self.test,
            82,
            self.pregunta,
            'Delegando y acompañando al equipo.',
        )
        self.url = reverse(
            'empresa_evaluar_participantes_ia',
            args=[self.plaza.id],
        )
        self.url_participantes = reverse(
            'empresa_invitar_participantes',
            args=[self.plaza.id],
        )
        self.url_asistente = reverse(
            'api_asistente_criterios_evaluacion',
            args=[self.plaza.id],
        )

    def _crear_persona(self, nombre, email, username):
        usuario = Usuario.objects.create(
            nombre_usuario=username,
            email=email,
            contrasena='clave',
            rol='profesional',
        )
        return Persona.objects.create(
            nombre=nombre,
            email=email,
            usuario=usuario,
        )

    def _crear_intento(
        self,
        persona,
        postulacion,
        test,
        puntaje,
        pregunta=None,
        respuesta='',
    ):
        intento = Intento.objects.create(
            persona=persona,
            test=test,
            postulacion=postulacion,
            estado=EstadoIntento.COMPLETADO,
            puntaje_total=puntaje,
        )
        if pregunta:
            Respuesta.objects.create(
                intento=intento,
                pregunta=pregunta,
                texto_respuesta=respuesta,
                tipo='texto',
                dimension=pregunta.dimension,
            )
        return intento

    def _resultado(self, puntaje=80, recomendacion='Apto'):
        return {
            'puntaje': puntaje,
            'recomendacion': recomendacion,
            'fortalezas': ['Liderazgo'],
            'brechas': ['Poco conocimiento técnico'],
            'informe': 'Informe generado para la prueba.',
            'modelo': 'gemini-2.5-flash',
        }

    def test_get_muestra_formulario_y_candidatos(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Evaluar participantes con IA')
        self.assertContains(response, 'Ana Pérez')
        self.assertContains(response, 'Experiencia en ventas y liderazgo')

    def test_otra_empresa_no_puede_acceder(self):
        otro_usuario = Usuario.objects.create(
            nombre_usuario='otra_empresa',
            email='otra@example.com',
            contrasena='clave',
            rol='empresa',
        )
        Empresa.objects.create(nombre='Otra Empresa', usuario=otro_usuario)
        otro_django_user = User.objects.create_user(
            username=otro_usuario.nombre_usuario,
            password='clave',
        )
        self.client.force_login(otro_django_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_post_sin_criterios_no_llama_a_gemini(self):
        with patch(
            'Reclutamente.views.evaluar_candidato_estructurado'
        ) as evaluar_mock:
            response = self.client.post(self.url, {'criterios': '   '})

        self.assertEqual(response.status_code, 200)
        evaluar_mock.assert_not_called()
        self.assertContains(
            response,
            'Selecciona un perfil, una competencia o escribe otros criterios',
        )

    @patch('Reclutamente.views.evaluar_candidato_estructurado')
    def test_post_evalua_y_guarda_analisis(self, evaluar_mock):
        evaluar_mock.return_value = self._resultado(91, 'Apto')

        response = self.client.post(
            self.url,
            {'criterios': 'Liderazgo y paciencia'},
        )

        self.assertEqual(response.status_code, 200)
        evaluar_mock.assert_called_once()
        kwargs = evaluar_mock.call_args.kwargs
        self.assertEqual(kwargs['criterios'], 'Liderazgo y paciencia')
        self.assertIn('¿Cómo manejas un equipo?', kwargs['respuestas_candidato'])
        self.assertIn('Delegando y acompañando al equipo.', kwargs['respuestas_candidato'])
        self.assertIn('Gerente de Ventas', kwargs['contexto_plaza'])

        analisis = AnalisisIA.objects.get(intento=self.intento)
        self.assertEqual(analisis.perfil['criterios'], 'Liderazgo y paciencia')
        self.assertEqual(analisis.perfil['puntaje'], 91)
        self.assertEqual(analisis.modelo_usado, 'gemini-2.5-flash')
        self.assertIn('Ana Pérez', response.content.decode())

    @patch('Reclutamente.views.evaluar_candidato_estructurado')
    def test_ranking_ordena_por_puntaje(self, evaluar_mock):
        beto = self._crear_persona('Beto Ruiz', 'beto@example.com', 'beto')
        postulacion_beto = Postulacion.objects.create(
            persona=beto,
            convocatoria=self.convocatoria,
        )
        self._crear_intento(
            beto,
            postulacion_beto,
            self.test,
            65,
            self.pregunta,
            'Coordinando al equipo.',
        )
        evaluar_mock.side_effect = [
            self._resultado(60, 'En revisión'),
            self._resultado(95, 'Apto'),
        ]

        response = self.client.post(
            self.url,
            {'criterios': 'Liderazgo'},
        )

        resultados = response.context['resultados_ia']
        self.assertEqual(
            [resultado['persona'].nombre for resultado in resultados],
            ['Beto Ruiz', 'Ana Pérez'],
        )
        self.assertEqual(resultados[0]['resultado']['puntaje'], 95)

    @patch('Reclutamente.views.evaluar_candidato_estructurado')
    def test_agrupa_varios_intentos_por_persona(self, evaluar_mock):
        segundo_test = Test.objects.create(
            nombre='Prueba de paciencia',
            categoria=self.categoria,
            estado=EstadoTest.PUBLICADO,
        )
        self._crear_intento(
            self.persona,
            self.postulacion,
            segundo_test,
            75,
        )
        evaluar_mock.return_value = self._resultado(88)

        self.client.post(self.url, {'criterios': 'Paciencia'})

        evaluar_mock.assert_called_once()
        evidencia = evaluar_mock.call_args.kwargs['respuestas_candidato']
        self.assertIn('Perfil comercial', evidencia)
        self.assertIn('Prueba de paciencia', evidencia)
        analisis = AnalisisIA.objects.get()
        self.assertEqual(len(analisis.perfil['intentos']), 2)

    @patch('Reclutamente.views.evaluar_candidato_estructurado')
    def test_error_de_gemini_no_cancela_otros_candidatos(self, evaluar_mock):
        beto = self._crear_persona('Beto Ruiz', 'beto@example.com', 'beto')
        postulacion_beto = Postulacion.objects.create(
            persona=beto,
            convocatoria=self.convocatoria,
        )
        self._crear_intento(
            beto,
            postulacion_beto,
            self.test,
            65,
        )
        evaluar_mock.side_effect = [
            Exception('fallo temporal'),
            self._resultado(70, 'En revisión'),
        ]

        response = self.client.post(self.url, {'criterios': 'Liderazgo'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AnalisisIA.objects.count(), 1)
        self.assertEqual(response.context['resultados_ia'][0]['persona'].nombre, 'Beto Ruiz')
        self.assertContains(response, 'No se pudieron evaluar 1 participante')

    @patch('Reclutamente.views.evaluar_candidato_estructurado')
    def test_sin_intentos_completados_no_llama_a_gemini(self, evaluar_mock):
        self.intento.estado = EstadoIntento.INICIADO
        self.intento.save(update_fields=['estado'])

        response = self.client.post(self.url, {'criterios': 'Liderazgo'})

        self.assertEqual(response.status_code, 200)
        evaluar_mock.assert_not_called()
        self.assertEqual(response.context['total_candidatos'], 0)
        self.assertContains(
            response,
            'Todavía no hay participantes para evaluar',
        )

    @patch('Reclutamente.views.evaluar_candidato_estructurado')
    def test_plaza_vencida_permite_evaluar_resultados(self, evaluar_mock):
        self.plaza.fecha_limite = timezone.localdate() - timedelta(days=1)
        self.plaza.save(update_fields=['fecha_limite'])
        evaluar_mock.return_value = self._resultado(84)

        response = self.client.post(self.url, {'criterios': 'Liderazgo'})

        self.assertEqual(response.status_code, 200)
        evaluar_mock.assert_called_once()
        self.assertEqual(AnalisisIA.objects.count(), 1)

    @patch('Reclutamente.views.evaluar_candidato_estructurado')
    def test_reevaluar_actualiza_el_mismo_analisis(self, evaluar_mock):
        evaluar_mock.return_value = self._resultado(70)

        self.client.post(self.url, {'criterios': 'Liderazgo'})
        evaluar_mock.return_value = self._resultado(90)
        self.client.post(self.url, {'criterios': 'Liderazgo y paciencia'})

        self.assertEqual(AnalisisIA.objects.count(), 1)
        analisis = AnalisisIA.objects.get()
        self.assertEqual(analisis.perfil['puntaje'], 90)
        self.assertEqual(
            analisis.perfil['criterios'],
            'Liderazgo y paciencia',
        )

    @patch('Reclutamente.views.evaluar_candidato_estructurado')
    def test_post_envia_y_guarda_sesgo_calificacion(self, evaluar_mock):
        evaluar_mock.return_value = self._resultado(85)

        self.client.post(
            self.url,
            {
                'criterios': 'Liderazgo',
                'sesgo': 'liderazgo',
                'sesgo_detalle': 'Priorizar iniciativa y toma de decisiones',
            },
        )

        kwargs = evaluar_mock.call_args.kwargs
        self.assertEqual(kwargs['sesgo_calificacion'], 'liderazgo')
        self.assertEqual(
            kwargs['sesgo_detalle'],
            'Priorizar iniciativa y toma de decisiones',
        )
        analisis = AnalisisIA.objects.get(intento=self.intento)
        self.assertEqual(analisis.perfil['sesgo'], 'liderazgo')

    def test_sesgo_invalido_se_normaliza_a_equilibrado(self):
        with patch(
            'Reclutamente.views.evaluar_candidato_estructurado'
        ) as evaluar_mock:
            evaluar_mock.return_value = self._resultado(80)
            self.client.post(
                self.url,
                {'criterios': 'Liderazgo', 'sesgo': 'no-existe'},
            )

        self.assertEqual(
            evaluar_mock.call_args.kwargs['sesgo_calificacion'],
            'equilibrado',
        )

    def test_pagina_participantes_muestra_casillas_de_evaluacion(self):
        response = self.client.get(self.url_participantes)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '¿Qué quieres evaluar?')
        self.assertContains(response, 'name="perfil_objetivo"')
        self.assertContains(response, 'name="competencias"')
        self.assertContains(response, 'name="otros_criterios"')
        self.assertContains(response, 'Líder de equipo')

    @patch('Reclutamente.views.evaluar_candidato_estructurado')
    def test_casillas_componen_criterios_y_guardan_seleccion(
        self, evaluar_mock
    ):
        evaluar_mock.return_value = self._resultado(88)

        response = self.client.post(
            self.url,
            {
                'perfil_objetivo': 'jefe',
                'competencias': ['liderazgo', 'comunicacion'],
                'otros_criterios': 'Experiencia en retail',
                'sesgo': 'potencial',
            },
        )

        self.assertEqual(response.status_code, 200)
        kwargs = evaluar_mock.call_args.kwargs
        self.assertIn('Perfil buscado: Jefe o gerente', kwargs['criterios'])
        self.assertIn('Liderazgo', kwargs['criterios'])
        self.assertIn('Comunicación', kwargs['criterios'])
        self.assertIn('Experiencia en retail', kwargs['criterios'])
        self.assertEqual(kwargs['sesgo_calificacion'], 'potencial')

        analisis = AnalisisIA.objects.get(intento=self.intento)
        self.assertEqual(analisis.perfil['perfil_objetivo'], 'jefe')
        self.assertEqual(
            analisis.perfil['competencias'],
            ['liderazgo', 'comunicacion'],
        )

        response = self.client.get(self.url_participantes)
        self.assertEqual(response.context['perfil_seleccionado'], 'jefe')
        self.assertEqual(
            response.context['competencias_seleccionadas'],
            ['liderazgo', 'comunicacion'],
        )
        self.assertEqual(response.context['sesgo_seleccionado'], 'potencial')

    @patch('Reclutamente.views.evaluar_candidato_estructurado')
    def test_textarea_de_criterios_tiene_prioridad_sobre_casillas(
        self, evaluar_mock
    ):
        evaluar_mock.return_value = self._resultado(80)

        self.client.post(
            self.url,
            {
                'criterios': 'Criterio escrito manualmente',
                'perfil_objetivo': 'especialista',
                'competencias': ['pensamiento_analitico'],
            },
        )

        kwargs = evaluar_mock.call_args.kwargs
        self.assertEqual(kwargs['criterios'], 'Criterio escrito manualmente')

    @patch('Reclutamente.views.evaluar_candidato_estructurado')
    def test_guarda_y_muestra_resultado_por_prueba(self, evaluar_mock):
        resultado = self._resultado(88)
        resultado['pruebas'] = [
            {
                'intento_id': self.intento.id,
                'test': 'Perfil comercial',
                'puntaje': 90,
                'fortalezas': ['Comunicación'],
                'brechas': ['Análisis numérico'],
                'informe': 'Buen desempeño específico en la prueba.',
            }
        ]
        evaluar_mock.return_value = resultado

        response = self.client.post(self.url, {'criterios': 'Liderazgo'})

        self.assertContains(response, 'Resultado por prueba')
        self.assertContains(
            response, 'Buen desempeño específico en la prueba.'
        )
        self.assertContains(response, 'Análisis numérico')

        analisis = AnalisisIA.objects.get(intento=self.intento)
        self.assertEqual(len(analisis.perfil['pruebas']), 1)
        self.assertEqual(
            analisis.perfil['pruebas'][0]['intento_id'], self.intento.id
        )
        self.assertEqual(analisis.perfil['pruebas'][0]['puntaje'], 90)

    def test_asistente_criterios_requiere_mensaje(self):
        response = self.client.post(
            self.url_asistente,
            data=json.dumps({}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)

    @patch('Reclutamente.views.asistente_criterios_evaluacion')
    def test_asistente_criterios_devuelve_criterios_y_sesgo(
        self, asistente_mock
    ):
        asistente_mock.return_value = {
            'respuesta': '¿Prefieres priorizar liderazgo o experiencia?',
            'criterios': 'Liderazgo, toma de decisiones',
            'sesgo': 'liderazgo',
            'sesgo_detalle': '',
            'listo': False,
        }

        response = self.client.post(
            self.url_asistente,
            data=json.dumps({'mensaje': 'Quiero liderazgo'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        datos = response.json()
        self.assertEqual(datos['sesgo'], 'liderazgo')
        self.assertEqual(datos['criterios'], 'Liderazgo, toma de decisiones')
        kwargs = asistente_mock.call_args.kwargs
        self.assertEqual(kwargs['mensaje'], 'Quiero liderazgo')
        self.assertIn('Gerente de Ventas', kwargs['contexto_plaza'])

    def test_otra_empresa_no_puede_usar_asistente(self):
        otro_usuario = Usuario.objects.create(
            nombre_usuario='otra_empresa_ia',
            email='otra_ia@example.com',
            contrasena='clave',
            rol='empresa',
        )
        Empresa.objects.create(nombre='Otra IA', usuario=otro_usuario)
        otro_django_user = User.objects.create_user(
            username=otro_usuario.nombre_usuario,
            password='clave',
        )
        self.client.force_login(otro_django_user)

        response = self.client.post(
            self.url_asistente,
            data=json.dumps({'mensaje': 'Liderazgo'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)


class FinalizarPruebaTest(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create(
            nombre_usuario='profesional_finaliza',
            email='profesional_finaliza@example.com',
            contrasena='clave',
            rol='profesional',
        )
        self.persona = Persona.objects.create(
            nombre='Profesional Finaliza',
            email=self.usuario.email,
            usuario=self.usuario,
        )
        self.django_user = User.objects.create_user(
            username=self.usuario.nombre_usuario,
            password='clave',
        )
        self.client.force_login(self.django_user)

        self.categoria = Categoria.objects.create(nombre='Razonamiento')
        self.test = Test.objects.create(
            nombre='Prueba de razonamiento',
            categoria=self.categoria,
            estado=EstadoTest.PUBLICADO,
        )
        self.pregunta = Pregunta.objects.create(
            texto_pregunta='¿Cómo resuelves un problema complejo?',
            dimension='Razonamiento',
            test=self.test,
        )

    def test_finalizar_prueba_guarda_intento_y_respuestas(self):
        response = self.client.post(
            reverse('test', args=[self.test.id]),
            {f'valor_{self.pregunta.id}': '4'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('home_profesionales'))
        intento = Intento.objects.get(
            persona=self.persona,
            test=self.test,
        )
        self.assertEqual(intento.estado, EstadoIntento.COMPLETADO)
        self.assertEqual(intento.puntaje_total, 4)
        self.assertTrue(
            Respuesta.objects.filter(
                intento=intento,
                pregunta=self.pregunta,
                texto_respuesta='4',
            ).exists()
        )
