from django.shortcuts import render


def legal_index(request):
    return render(request, 'legal/index.html', {'page_title': 'Centro legal'})


def legal_aviso(request):
    return render(request, 'legal/aviso_legal.html', {'page_title': 'Aviso Legal'})


def legal_terminos(request):
    return render(request, 'legal/terminos_condiciones.html', {'page_title': 'Términos y Condiciones'})


def legal_privacidad(request):
    return render(request, 'legal/politica_privacidad.html', {'page_title': 'Política de Privacidad'})


def legal_cookies(request):
    return render(request, 'legal/politica_cookies.html', {'page_title': 'Política de Cookies'})


def legal_consentimiento(request):
    return render(request, 'legal/consentimiento_datos.html', {'page_title': 'Consentimiento de tratamiento de datos'})
