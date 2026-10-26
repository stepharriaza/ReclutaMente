from django.contrib import admin
from django.urls import path
from . import views

urlpatterns = [
    path(
        'admin/', 
        admin.site.urls),
        
    path(
        '', 
        views.home, 
        name='home'),
    
    path(
        'catalogo/', 
        views.catalogo, 
        name='catalogo'
    ),
    
    path(
        'catalogo/<int:categoria_id>/',
        views.tests_categoria,
        name='tests_categoria',
    ),
    path(
        'test/<int:test_id>/', 
        views.test, 
        name='test'),
    
    path(
        'registro/', 
        views.registro_view, 
        name='registro'),
    
    path(
        'logout/', 
        views.logout_view, 
        name='logout'),
    
    path(
        'login/', 
        views.login_view, 
        name='login'),
    
    path(
        'qr/vacante/<str:codigo_unico>/', 
        views.generar_qr_vacante, 
        name='generar_qr_vacante'),
    
    path(
        'evaluacion/vacante/<str:codigo_unico>/', 
        views.evaluar_vacante_protegida, 
        name='evaluar_vacante_protegida'),

    path(
        'evaluacion/invitacion/<str:token>/',
        views.evaluacion_invitacion,
        name='evaluacion_invitacion'),

    path(
        'empresa/vacantes/<int:pk>/participantes/',
        views.empresa_invitar_participantes,
        name='empresa_invitar_participantes'),
    # URL Super admin
    path(
        'superadmin/perfil/', 
        views.superadmin_perfil, 
        name='superadmin_perfil'),
    
    path(
        'superadmin/tickets/', 
        views.superadmin_tickets, 
        name='superadmin_tickets'
    ),

    path(
        'superadmin/tickets/detalle/<int:pk>/',
        views.superadmin_ticket_detalle,
        name='superadmin_ticket_detalle',
    ),
    path(
        'superadmin/empresas/',
        views.superadmin_empresas,
        name='superadmin_empresas',
    ),
    path(
        'superadmin/empresas/detalle/<int:pk>/',
        views.superadmin_empresa_detalle,
        name='superadmin_empresa_detalle',
    ),
    path(
        'superadmin/empresas/supervision-ia/<int:pk>/',
        views.superadmin_empresas_ia,
        name='superadmin_supervision_ia',
    ),
    path(
        'superadmin/profesionales/',
        views.superadmin_profesionales,
        name='superadmin_profesionales',
    ),
    path(
        'superadmin/profesionales/<int:pk>/toggle/',
        views.superadmin_toggle_profesional,
        name='superadmin_toggle_profesional',
    ),
    path(
        'superadmin/bitacora/',
        views.superadmin_bitacora,
        name='superadmin_bitacora',
    ),
    path(
        'superadmin/tickets/<int:pk>/cancelar/',
        views.superadmin_ticket_cancelar,
        name='superadmin_ticket_cancelar',
    ),
    path(
        'superadmin/tickets/<int:pk>/modificar/',
        views.superadmin_ticket_modificar,
        name='superadmin_ticket_modificar',
    ),
    path(
        'superadmin/profesionales/crear/',
        views.superadmin_crear_profesional,
        name='superadmin_crear_profesional',
    ),
    path(
        'superadmin/dashboard/',
        views.superadmin_dashboard,
        name='superadmin_dashboard',
    ),
    path(
        'superadmin/empresas/editar/<int:pk>/',
        views.superadmin_empresa_editar,
        name='superadmin_empresa_editar',
    ),
    path(
        'superadmin/empresas/reporte-consumo/<int:pk>/',
        views.superadmin_reporte_consumo,
        name='superadmin_reporte_consumo',
    ),
    # --- VISTAS DE EMPRESAS ---
    path('empresa/dashboard/', views.empresa_dashboard, name='empresa_dashboard'),
    path('empresa/vacantes/', views.empresa_vacantes, name='empresa_vacantes'),
    path(
        'empresa/vacantes/crear/',
        views.empresa_crear_vacante,
        name='empresa_crear_vacante',
    ),
    path('empresa/perfil/', views.empresa_perfil, name='empresa_perfil'),
    path(
        'empresa/vacantes/editar/<int:pk>/',
        views.empresa_editar_vacante,
        name='empresa_editar_vacante',
    ),
    path('empresa/soporte/', views.empresa_tickets, name='empresa_tickets'),
    # --- VISTAS DE PROFESIONALES ---
    path(
        'profesional/', views.home_profesionales, name='home_profesionales'
    ),
    path(
        'profesional/perfil/',
        views.profesional_perfil,
        name='profesional_perfil',
    ),
    # --- Agente de IA ---
    path('api/agente-ia/', views.api_agente_ia, name='api_agente_ia'),
    path(
        'api/crear-prueba-ia/',
        views.api_crear_prueba_ia,
        name='api_crear_prueba_ia',
    ),
    path(
        'api/agente-interactivo/',
        views.api_agente_interactivo,
        name='api_agente_interactivo',
    ),
    path(
        'api/evaluar-candidato/',
        views.evaluar_candidato_view,
        name='evaluar_candidato',
    ),
]