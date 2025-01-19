# Company Employee Count Analyzer

This web application allows users to upload a CSV file containing company names, search for the number of employees using the Claude API, and receive an updated CSV file with employee counts.

## Features

- Upload CSV files
- Select country from Asia and Australia region
- Process company data using Claude API
- Download updated CSV file with employee counts

## Prerequisites

- Node.js (v16 or higher)
- Python (v3.8 or higher)
- pip (Python package manager)
- npm (Node.js package manager)

## Installation

### Backend Setup

1. Create and activate a Python virtual environment (optional but recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows, use: venv\Scripts\activate
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
Create a `.env` file in the root directory and add your Anthropic API key:
```
ANTHROPIC_API_KEY=your_api_key_here
```

### Frontend Setup

1. Navigate to the frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

## Running the Application

1. Start the Flask backend (from the root directory):
```bash
python backend/app.py
```

2. Start the React frontend (in a new terminal):
```bash
cd frontend
npm run dev
```

3. Open your browser and navigate to `http://localhost:5173`

## Usage

1. Click "Upload CSV File" to select your CSV file containing company names
2. Select a country from the dropdown menu
3. Click "Process File" to start the analysis
4. Wait for the processing to complete
5. The updated CSV file will automatically download when ready

## CSV File Format

The input CSV file should have a column named "Company Name". The output file will include this column plus a new "Number of Employees" column.

Example input CSV:
```csv
Company Name
Apple Inc.
Samsung Electronics
Toyota Motor Corporation
```

Example output CSV:
```csv
Company Name,Number of Employees
Apple Inc.,25000
Samsung Electronics,45000
Toyota Motor Corporation,30000
```

## Error Handling

The application includes error handling for:
- Invalid file formats
- Missing company names
- API failures
- Network issues

## Technologies Used

- Frontend: React, Material-UI, Axios
- Backend: Flask, Anthropic API
- File Processing: Python CSV module
