import os
import time
from django.conf import settings
from google import genai
from google.genai import types


def generar_contenido_seguro(prompt_texto):
  client = genai.Client(api_key=settings.GEMINI_API_KEY)

  modelos_disponibles = [
      'gemini-2.0-flash',
      'gemini-flash-latest',
  ]

  intentos_maximos = 3
  ultimo_error = None

  for modelo in modelos_disponibles:
    for intento in range(intentos_maximos):
      try:
        response = client.models.generate_content(
            model=modelo,
            contents=prompt_texto,
        )
        if response and response.text:
          return response.text
      except Exception as e:
        ultimo_error = str(e)
        if '503' in str(e) or 'UNAVAILABLE' in str(e):
          time.sleep(2 * (intento + 1))
          continue
        break

  raise Exception(
      f'No se pudo conectar tras varios reintentos. Último error:'
      f' {ultimo_error}'
  )


def obtener_cliente_gemini():
  return genai.Client(api_key=os.environ.get('GEMINI_API_KEY'))


def generar_o_modificar_prueba(necesidades_empresa, tipo_prueba):
  """Fase 1: Ayuda a la empresa a diseñar o modificar encuestas/pruebas psicométricas."""
  client = obtener_cliente_gemini()

  system_instruction = """
    Eres un asistente experto en diseño instruccional y psicología organizacional para la plataforma ReclutaMente.
    Tu trabajo es ayudar a las empresas a crear o modificar cuestionarios y pruebas psicométricas 
    a la medida, adaptados exactamente a las competencias y necesidades que la empresa solicita para su vacante.
    Entrega las preguntas de forma estructurada y clara.
    """

  prompt = f"""
    Requisitos y necesidades de la empresa: {necesidades_empresa}
    Tipo de prueba base: {tipo_prueba}
    
    Por favor, genera o ajusta las preguntas de la prueba evaluando las competencias clave requeridas.
    """

  response = client.models.generate_content(
      model='gemini-2.5-flash',
      contents=prompt,
      config=types.GenerateContentConfig(
          system_instruction=system_instruction,
          temperature=0.4,
      ),
  )
  return response.text


def evaluar_candidato_con_criterios_empresa(
    respuestas_candidato, requisitos_vacante, nombre_archivo_guia=None
):
  """Analiza las respuestas del candidato cruzándolas con los requisitos

  y una guía específica según el tipo de prueba.
  """
  client = genai.Client(api_key=os.environ.get('GEMINI_API_KEY'))

  system_instruction = """
    Eres un evaluador psicométrico experto de ReclutaMente. Tu labor es analizar las respuestas 
    del candidato cruzándolas estrictamente con los requisitos de la vacante y con la guía específica 
    de evaluación asignada para esta prueba.
    Entrega un reporte estructurado que incluya:
    1. Puntuación numérica (0 a 100).
    2. Fortalezas principales.
    3. Áreas de mejora / brechas.
    4. Recomendación final de contratación (Apto, En revisión, No apto).
    """

  contents = []
  archivo_ref = None

  # Si se especificó una guía y existe, la cargamos dinámicamente usando la variable
  if nombre_archivo_guia:
    ruta_documento = os.path.join(
        settings.BASE_DIR, 'core', 'guias_ia', nombre_archivo_guia
    )
    if os.path.exists(ruta_documento):
      archivo_ref = client.files.upload(file=ruta_documento)
      contents.append(archivo_ref)

  prompt = f"""
    Requisitos de la empresa para la vacante: {requisitos_vacante}
    
    Respuestas dadas por el candidato:
    {respuestas_candidato}
    
    Por favor, realiza el análisis psicométrico cruzado basándote en la guía provista y estos parámetros.
    """
  contents.append(prompt)

  response = client.models.generate_content(
      model='gemini-2.5-flash',
      contents=contents,
      config=types.GenerateContentConfig(
          system_instruction=system_instruction,
          temperature=0.2,
      ),
  )

  if archivo_ref:
    client.files.delete(name=archivo_ref.name)

  return response.text