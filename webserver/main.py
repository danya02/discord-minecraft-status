from flask import Flask, abort, make_response
import redis

app = Flask(__name__)

db = redis.Redis(host='redis')

@app.route('/<file>')
def serve_file(file):
    result = db.get(file)
    if result is None:
        return abort(404)
    result = make_response(result)
    result.mimetype='image/'+file.split('.')[-1]
    return result
