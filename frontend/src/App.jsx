import { useState, useEffect } from 'react'
import { 
  Box, 
  Button, 
  Container, 
  FormControl, 
  InputLabel, 
  MenuItem, 
  Select, 
  Typography,
  CircularProgress,
  Alert,
  LinearProgress,
  Paper
} from '@mui/material'
import axios from 'axios'

// Update API URL to use port 5001
const API_URL = 'http://localhost:5001';

function App() {
  const [file, setFile] = useState(null)
  const [country, setCountry] = useState('')
  const [countries, setCountries] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [progress, setProgress] = useState(0)
  const [processingStatus, setProcessingStatus] = useState('')

  useEffect(() => {
    const fetchCountries = async () => {
      try {
        console.log('API Base URL:', API_URL)
        console.log('Fetching countries from:', `${API_URL}/api/countries`)
        const response = await axios.get(`${API_URL}/api/countries`)
        console.log('Countries response:', response.data)
        setCountries(response.data)
      } catch (error) {
        console.error('Error fetching countries:', error)
        if (error.response) {
          console.error('Response data:', error.response.data)
          console.error('Response status:', error.response.status)
          console.error('Response headers:', error.response.headers)
        } else if (error.request) {
          console.error('Request made but no response:', error.request)
        } else {
          console.error('Error setting up request:', error.message)
        }
        setError('Failed to load countries. Please try again later.')
        setCountries([])
      }
    }

    fetchCountries()
  }, [])

  const handleFileChange = (event) => {
    const selectedFile = event.target.files[0]
    console.log('Selected file:', selectedFile)
    if (selectedFile && selectedFile.name.endsWith('.csv')) {
      // Read file to count number of companies for progress calculation
      const reader = new FileReader()
      reader.onload = (e) => {
        const content = e.target.result
        const lines = content.split('\n').length - 1 // Subtract header row
        setFile(selectedFile)
        setProcessingStatus(`Found ${lines} companies to process`)
      }
      reader.readAsText(selectedFile)
      setError(null)
    } else {
      setError('Please select a valid CSV file')
      setFile(null)
    }
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    
    if (!file || !country) {
      setError('Please select both a file and a country')
      return
    }

    setLoading(true)
    setError(null)
    setProgress(0)
    setProcessingStatus('Starting processing...')

    const formData = new FormData()
    formData.append('file', file)
    formData.append('country', country)

    try {
      console.log('API Base URL:', API_URL)
      console.log('Submitting file:', file.name, 'for country:', country)
      const response = await axios.post(`${API_URL}/api/process`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        },
        onUploadProgress: (progressEvent) => {
          const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
          setProgress(percentCompleted)
          setProcessingStatus(`Uploading file: ${percentCompleted}%`)
        }
      })

      if (response.headers['content-type']?.includes('application/json')) {
        // Handle error response
        if (response.data.error) {
          throw new Error(response.data.error);
        }
      } else if (response.headers['content-type']?.includes('text/csv')) {
        console.log('Received CSV response:', response.data)
        setProcessingStatus('Processing complete! Downloading file...')
        // Create download link
        const blob = new Blob([response.data], { type: 'text/csv' })
        const url = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.setAttribute('download', 'updated_companies.csv')
        document.body.appendChild(link)
        link.click()
        link.remove()
        window.URL.revokeObjectURL(url)
        setProcessingStatus('Done! File has been downloaded.')
      } else {
        throw new Error('Unexpected response type from server')
      }
    } catch (error) {
      console.error('Error processing file:', error)
      if (error.response) {
        console.error('Response data:', error.response.data)
        if (error.response.data instanceof Blob) {
          // Try to read the blob as text to get the error message
          const text = await error.response.data.text();
          try {
            const errorData = JSON.parse(text);
            setError(errorData.error || 'Failed to process file. Please try again later.');
          } catch (e) {
            setError('Failed to process file. Please try again later.');
          }
        } else {
          setError(error.response.data.error || 'Failed to process file. Please try again later.');
        }
      } else if (error.request) {
        console.error('Request made but no response:', error.request)
        setError('No response from server. Please try again later.');
      } else {
        console.error('Error setting up request:', error.message)
        setError(error.message || 'Failed to process file. Please try again later.');
      }
    } finally {
      setLoading(false)
      setProgress(0)
    }
  }

  return (
    <Container maxWidth="sm">
      <Box sx={{ mt: 4, mb: 4 }}>
        <Typography variant="h4" component="h1" gutterBottom>
          Company Employee Count Analyzer
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        <Paper elevation={3} sx={{ p: 3, mb: 3 }}>
          <form onSubmit={handleSubmit}>
            <Box sx={{ mb: 2 }}>
              <input
                accept=".csv"
                style={{ display: 'none' }}
                id="file-upload"
                type="file"
                onChange={handleFileChange}
              />
              <label htmlFor="file-upload">
                <Button variant="contained" component="span" fullWidth>
                  Upload CSV File
                </Button>
              </label>
              {file && (
                <Typography variant="body2" sx={{ mt: 1 }}>
                  Selected file: {file.name}
                </Typography>
              )}
              {processingStatus && (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  {processingStatus}
                </Typography>
              )}
            </Box>

            <FormControl fullWidth sx={{ mb: 2 }}>
              <InputLabel>Country</InputLabel>
              <Select
                value={country}
                label="Country"
                onChange={(e) => setCountry(e.target.value)}
              >
                {countries.map((country) => (
                  <MenuItem key={country.id} value={country.id}>
                    {country.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            {loading && progress > 0 && (
              <Box sx={{ mb: 2 }}>
                <LinearProgress variant="determinate" value={progress} />
              </Box>
            )}

            <Button
              type="submit"
              variant="contained"
              color="primary"
              fullWidth
              disabled={loading || !file || !country}
            >
              {loading ? <CircularProgress size={24} /> : 'Process File'}
            </Button>
          </form>
        </Paper>
      </Box>
    </Container>
  )
}

export default App
