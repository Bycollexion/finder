def handler(request):
    countries = ["United States", "China", "India", "United Kingdom", "Germany"]  # Example list
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": countries
    }
