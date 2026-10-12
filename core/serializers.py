from rest_framework import serializers

class EmpresaSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    nombre = serializers.CharField(max_length=150)
    plan = serializers.CharField(max_length=50)
    consumo = serializers.CharField(max_length=20)
    estado = serializers.CharField(max_length=20)


class TicketSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    empresa = serializers.CharField(max_length=150)
    asunto = serializers.CharField(max_length=200)
    prioridad = serializers.CharField(max_length=50) 
    estado = serializers.CharField(max_length=50)     
    fecha = serializers.CharField(max_length=50)

