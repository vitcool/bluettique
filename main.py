from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Access the variables
device_key = os.getenv("DEVICE_KEY")
login_user = os.getenv("LOGIN_USER")
login_password = os.getenv("LOGIN_PASSWORD")

print(f"Using device key: {device_key}")
print(f"Using login user: {login_user}")
print(f"Using login password: {login_password}")
