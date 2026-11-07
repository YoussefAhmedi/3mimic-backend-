from rest_framework import serializers


class AnswerSerializer(serializers.Serializer):
    selected = serializers.IntegerField(min_value=1)  # 1 = the first option
    index = serializers.IntegerField(min_value=0, required=False)  # optional sanity check from the client
