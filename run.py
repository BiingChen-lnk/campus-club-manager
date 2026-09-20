import os
from clubapp import create_app

app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.getenv('DBXM_PORT', '5000')), debug=False)
