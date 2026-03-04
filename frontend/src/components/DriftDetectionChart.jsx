import React, { useState, useEffect } from 'react';
import {
  Box,
  VStack,
  HStack,
  Grid,
  GridItem,
  Card,
  CardBody,
  CardHeader,
  Heading,
  Text,
  Badge,
  Select,
  FormControl,
  FormLabel,
  Spinner,
  Center,
} from '@chakra-ui/react';

/**
 * DriftDetectionChart - Visualizes concept drift detection across sensors
 *
 * Shows:
 * - Drift index per sensor (KL divergence or PSI)
 * - Distribution changes over time
 * - Severity badges (LOW/MEDIUM/HIGH)
 * - Baseline vs current comparison
 */
export default function DriftDetectionChart({ machineId = null }) {
  const [selectedSensor, setSelectedSensor] = useState('Cushion');
  const [driftData, setDriftData] = useState(null);
  const [loading, setLoading] = useState(false);

  const commonSensors = [
    'Cushion',
    'Injection_time',
    'Intensity',
    'Back_pressure',
    'Mold_temperature',
  ];

  useEffect(() => {
    loadDriftData();
  }, [selectedSensor, machineId]);

  const loadDriftData = async () => {
    setLoading(true);
    try {
      // In a real implementation, this would call the backend
      // For now, showing placeholder data structure
      const mockData = {
        sensor_name: selectedSensor,
        machine_id: machineId,
        eval_windows: [
          {
            window: '1h',
            mean_baseline: 50.2,
            std_baseline: 5.3,
            mean_current: 51.1,
            std_current: 5.8,
            drift_index: 0.12,
            drift_severity: 'LOW',
          },
          {
            window: '1d',
            mean_baseline: 50.0,
            std_baseline: 5.1,
            mean_current: 52.3,
            std_current: 6.2,
            drift_index: 0.35,
            drift_severity: 'MEDIUM',
          },
          {
            window: '1w',
            mean_baseline: 49.8,
            std_baseline: 5.0,
            mean_current: 53.5,
            std_current: 6.5,
            drift_index: 0.62,
            drift_severity: 'HIGH',
          },
        ],
      };

      setDriftData(mockData);
    } catch (error) {
      console.error('Failed to load drift data:', error);
    } finally {
      setLoading(false);
    }
  };

  const getDriftSeverityColor = (severity) => {
    if (severity === 'HIGH') return 'red';
    if (severity === 'MEDIUM') return 'orange';
    return 'green';
  };

  return (
    <VStack align="stretch" spacing={4}>
      {/* Sensor Selector */}
      <FormControl maxW="250px">
        <FormLabel fontSize="sm">Select Sensor</FormLabel>
        <Select
          value={selectedSensor}
          onChange={(e) => setSelectedSensor(e.target.value)}
        >
          {commonSensors.map((sensor) => (
            <option key={sensor} value={sensor}>
              {sensor}
            </option>
          ))}
        </Select>
      </FormControl>

      {/* Drift Analysis Cards */}
      {loading ? (
        <Center p={8}>
          <Spinner />
        </Center>
      ) : driftData ? (
        <Grid templateColumns="repeat(auto-fit, minmax(300px, 1fr))" gap={4}>
          {driftData.eval_windows.map((window) => (
            <Card key={window.window} bg="gray.50">
              <CardHeader>
                <HStack justify="space-between">
                  <Heading size="md">Window: {window.window}</Heading>
                  <Badge colorScheme={getDriftSeverityColor(window.drift_severity)}>
                    {window.drift_severity}
                  </Badge>
                </HStack>
              </CardHeader>
              <CardBody>
                <VStack align="stretch" spacing={3}>
                  {/* Drift Index */}
                  <Box>
                    <Text fontSize="xs" color="gray.600" mb={1}>
                      Drift Index (KL Divergence)
                    </Text>
                    <Text fontSize="xl" fontWeight="bold">
                      {window.drift_index.toFixed(3)}
                    </Text>
                    <Text fontSize="xs" color="gray.500" mt={1}>
                      {window.drift_index < 0.2
                        ? 'No significant drift detected'
                        : window.drift_index < 0.5
                          ? 'Moderate drift detected'
                          : 'Significant drift detected'}
                    </Text>
                  </Box>

                  {/* Distribution Comparison */}
                  <Box
                    p={3}
                    bg="white"
                    borderRadius="md"
                    borderLeft="4px"
                    borderColor="blue.500"
                  >
                    <Grid templateColumns="1fr 1fr" gap={2} fontSize="xs">
                      <Box>
                        <Text fontWeight="bold" color="blue.600" mb={1}>
                          Baseline (7d ago)
                        </Text>
                        <Text>
                          μ = {window.mean_baseline.toFixed(2)}
                        </Text>
                        <Text>
                          σ = {window.std_baseline.toFixed(2)}
                        </Text>
                      </Box>
                      <Box>
                        <Text fontWeight="bold" color="green.600" mb={1}>
                          Current
                        </Text>
                        <Text>
                          μ = {window.mean_current.toFixed(2)}
                        </Text>
                        <Text>
                          σ = {window.std_current.toFixed(2)}
                        </Text>
                      </Box>
                    </Grid>
                  </Box>

                  {/* Change Indicators */}
                  <Grid templateColumns="1fr 1fr" gap={2} fontSize="xs">
                    <Box>
                      <Text color="gray.600">μ Change</Text>
                      <Text fontWeight="bold" color={
                        Math.abs(window.mean_current - window.mean_baseline) > 1
                          ? 'orange.600'
                          : 'green.600'
                      }>
                        {(window.mean_current - window.mean_baseline).toFixed(2)}
                        {' '}({(((window.mean_current - window.mean_baseline) / window.mean_baseline) * 100).toFixed(1)}%)
                      </Text>
                    </Box>
                    <Box>
                      <Text color="gray.600">σ Change</Text>
                      <Text fontWeight="bold" color={
                        Math.abs(window.std_current - window.std_baseline) > 1
                          ? 'orange.600'
                          : 'green.600'
                      }>
                        {(window.std_current - window.std_baseline).toFixed(2)}
                        {' '}({(((window.std_current - window.std_baseline) / window.std_baseline) * 100).toFixed(1)}%)
                      </Text>
                    </Box>
                  </Grid>

                  {/* Recommendations */}
                  {window.drift_severity === 'HIGH' && (
                    <Box
                      p={2}
                      bg="red.50"
                      borderRadius="md"
                      borderLeft="3px"
                      borderColor="red.500"
                    >
                      <Text fontSize="xs" color="red.700" fontWeight="bold">
                        ⚠️ High Drift Alert
                      </Text>
                      <Text fontSize="xs" color="red.600" mt={1}>
                        Consider retraining models or adjusting control limits
                      </Text>
                    </Box>
                  )}
                </VStack>
              </CardBody>
            </Card>
          ))}
        </Grid>
      ) : (
        <Center p={8} color="gray.400">
          No drift data available
        </Center>
      )}

      {/* Information Box */}
      <Box bg="gray.50" p={4} borderRadius="md">
        <VStack align="stretch" spacing={2}>
          <Text fontWeight="bold" fontSize="sm">
            📊 How Drift Detection Works
          </Text>
          <Text fontSize="xs" color="gray.600">
            • Baseline: Distribution from 7 days ago
          </Text>
          <Text fontSize="xs" color="gray.600">
            • Current: Distribution from recent data
          </Text>
          <Text fontSize="xs" color="gray.600">
            • Drift Index (KL): Measures statistical distribution divergence
          </Text>
          <Text fontSize="xs" color="gray.600">
            • HIGH: &gt; 0.5 | MEDIUM: 0.2-0.5 | LOW: &lt; 0.2
          </Text>
        </VStack>
      </Box>
    </VStack>
  );
}
