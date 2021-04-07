from flask import Flask
import redis

app = Flask(__main__)

@app.route('/<file>')
def serve_file(file):
    return redis.get(file)
