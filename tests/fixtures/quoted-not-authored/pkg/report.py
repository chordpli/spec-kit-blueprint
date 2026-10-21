# The response shape was settled when this handler was written (OQ-4).
def handle(request):
    return {"body": request.get("body", "")}
