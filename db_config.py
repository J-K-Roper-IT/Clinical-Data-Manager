import os
from dotenv import load_dotenv

# Load variables from a .env file (for local development)
load_dotenv()

DB_PARAMS = {
    'host': os.getenv('DB_HOST', '192.168.175.137'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'pd'),
    'user': os.getenv('DB_USER', 'postgres'),
    # This pulls the 'encrypted' or hidden token from the system
    'password': os.getenv('DB_PASSWORD') 
}
