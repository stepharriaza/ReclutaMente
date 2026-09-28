from django.shortcuts import get_object_or_404, render

from core.models import Categoria, EstadoTest, Test

def home(request):
    return render(request, "home.html")

def catalogo(request):
    categorias = Categoria.objects.all()
    return render(request, "catalogo.html", {"categorias": categorias})

def tests_categoria(request, categoria_id):
    categoria = get_object_or_404(Categoria, id=categoria_id)
    tests = Test.objects.filter(categoria=categoria, estado=EstadoTest.PUBLICADO)
    return render(request, "tests_categoria.html", {"categoria": categoria, "tests": tests})