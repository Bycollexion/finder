import { useState, useEffect } from 'react'
import {
  Container,
  Paper,
  Typography,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Box,
  CircularProgress,
  Alert,
  Snackbar
} from '@mui/material'
import axios from 'axios'

// Update API URL to use server IP
const API_URL = 'http://192.168.1.20:5001';

// Configure axios defaults
axios.defaults.withCredentials = true;
axios.defaults.headers.common['Content-Type'] = 'application/json';

function App() {
  const [file, setFile] = useState(null)
  const [country, setCountry] = useState('')
  const [countries, setCountries] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(false)
  const [progress, setProgress] = useState(0)
  const [processingStatus, setProcessingStatus] = useState('')

  useEffect(() => {
    const fetchCountries = async () => {
      try {
        setLoading(true)
        setError(null)
        console.log('API Base URL:', API_URL)
        console.log('Fetching countries from:', `${API_URL}/api/countries`)
        const response = await axios.get(`${API_URL}/api/countries`, {
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
          }
        })
        console.log('Countries response:', response.data)
        setCountries(response.data)
      } catch (error) {
        console.error('Error fetching countries:', error)
        setError('Failed to load countries. Please try again later. ' + (error.response?.data?.error || error.message))
      } finally {
        setLoading(false)
      }
    }

    fetchCountries()
  }, [])

  const handleFileChange = (event) => {
    const selectedFile = event.target.files[0]
    if (selectedFile) {
      if (selectedFile.type === 'text/csv' || selectedFile.name.endsWith('.csv')) {
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
        setError('Please upload a CSV file')
        setFile(null)
      }
    }
  }

  const handleCountryChange = (event) => {
    setCountry(event.target.value)
    setError(null)
  }

  const handleSubmit = async () => {
    if (!file) {
      setError('Please select a file')
      return
    }
    if (!country) {
      setError('Please select a country')
      return
    }

    const formData = new FormData()
    formData.append('file', file)
    formData.append('country', country)

    try {
      setLoading(true)
      setError(null)
      console.log('API Base URL:', API_URL)
      console.log('Submitting file:', file.name, 'for country:', country)
      const response = await axios.post(`${API_URL}/api/process`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        },
        withCredentials: true,
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
        // Create a download link
        const blob = new Blob([response.data], { type: 'text/csv' })
        const url = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = 'updated_companies.csv'
        document.body.appendChild(link)
        link.click()
        link.remove()
        window.URL.revokeObjectURL(url)
        setProcessingStatus('Done! File has been downloaded.')
        setSuccess(true)
      } else {
        throw new Error('Unexpected response type from server')
      }
    } catch (error) {
      console.error('Error processing file:', error)
      setError('Failed to process file. ' + (error.response?.data?.error || error.message))
    } finally {
      setLoading(false)
      setProgress(0)
    }
  }

  return (
    <Container maxWidth="sm" sx={{ mt: 4 }}>
      <Paper elevation={3} sx={{ p: 3 }}>
        <Typography variant="h4" gutterBottom>
          Employee Count Finder
        </Typography>

        {/* File Upload */}
        <Box sx={{ mb: 3 }}>
          <input
            accept=".csv"
            style={{ display: 'none' }}
            id="file-upload"
            type="file"
            onChange={handleFileChange}
          />
          <label htmlFor="file-upload">
            <Button variant="contained" component="span" fullWidth>
              Upload CSV
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

        {/* Country Selection */}
        <FormControl fullWidth sx={{ mb: 3 }}>
          <InputLabel>Country</InputLabel>
          <Select value={country} onChange={handleCountryChange} label="Country">
            {countries.map((country) => (
              <MenuItem key={country.id} value={country.id}>
                {country.name}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        {/* Submit Button */}
        <Button
          variant="contained"
          color="primary"
          fullWidth
          onClick={handleSubmit}
          disabled={loading || !file || !country}
        >
          {loading ? <CircularProgress size={24} /> : 'Process File'}
        </Button>

        {/* Error Message */}
        <Snackbar 
          open={!!error} 
          autoHideDuration={6000} 
          onClose={() => setError(null)}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        >
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        </Snackbar>

        {/* Success Message */}
        <Snackbar
          open={success}
          autoHideDuration={6000}
          onClose={() => setSuccess(false)}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        >
          <Alert severity="success" onClose={() => setSuccess(false)}>
            File processed successfully!
          </Alert>
        </Snackbar>

        {/* Progress Bar */}
        {loading && progress > 0 && (
          <Box sx={{ mt: 2 }}>
            <LinearProgress variant="determinate" value={progress} />
          </Box>
        )}
      </Paper>
    </Container>
  )
}

export default App
