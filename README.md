# bluettique

To be updated...

## Table of Contents

- Installation
- Environment Variables
- Running the Project
- Dependencies

## Installation

1. Clone the repository:

   `git clone https://github.com/your-username/your-repo.git`

2. Navigate to the project directory:

   `cd your-repo`

3. Set up a virtual environment:

   - **Linux/macOS**:

     `python3 -m venv venv`

     `source venv/bin/activate`

   - **Windows**:

     `python -m venv venv`

     `venv\Scripts\activate`

4. Install the required dependencies:

   `pip install -r requirements.txt`

## Environment Variables

This project requires some environment variables to be set. These variables are stored in a `.env` file in the root of the project.

Create a `.env` file in the root of the project and add the following variables:

```
DEVICE_KEY=your_device_key
LOGIN_USER=your_username
LOGIN_PASSWORD=your_password
```

Make sure to replace `your_device_key`, `your_username`, and `your_password` with your actual credentials.

## Running the Project

1. Activate the virtual environment (if not already activated):

   - **Linux/macOS**: `source venv/bin/activate`
   
   - **Windows**: `venv\Scripts\activate`

2. Run the application:

   `python main.py`

## Dependencies

All dependencies are listed in the `requirements.txt` file. To install them, use:

`pip install -r requirements.txt`

