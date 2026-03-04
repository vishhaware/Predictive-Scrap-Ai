import React, { useState, useEffect } from 'react';
import Plot from 'react-plotly.js';
import {
  Box,
  VStack,
  HStack,
  FormControl,
  FormLabel,
  Select,
  Button,
  Text,
  Spinner,
  Center,
  Card,
  CardBody,
  Grid,
} from '@chakra-ui/react';
import { useTelemetryStore } from '../store/useTelemetryStore';

/**
 * ConfidenceZoneChart - Prediction with confidence bands visualization
 *
 * Features:
 * - Main prediction line (center)
 * - Upper confidence band (2σ)
 * - Lower confidence band (2σ)
 * - Actual scrap events overlay (red for scrap, green for good)
 * - Model selector
 * - Time range controls
 */
export default function ConfidenceZoneChart({
  machineId = null,
  timeRangeHours = 24,
}) {
  const { machines, loadPredictions } = useTelemetryStore();
  const [selectedMachine, setSelectedMachine] = useState(machineId);
  const [selectedModel, setSelectedModel] = useState('lightgbm_v1');
  const [timeRange, setTimeRange] = useState(timeRangeHours);
  const [chartData, setChartData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showActualEvents, setShowActualEvents] = useState(true);
  const [showConfidenceBands, setShowConfidenceBands] = useState(true);

  const models = [
    { id: 'lightgbm_v1', name: 'LightGBM Classifier (v1)' },
    { id: 'lstm_attention_dual', name: 'LSTM Attention (Dual)' },
  ];

  useEffect(() => {
    loadChartData();
  }, [selectedMachine, selectedModel, timeRange]);

  const loadChartData = async () => {
    setLoading(true);
    try {
      // Simulate loading chart data
      // In production: const data = await fetch(`/api/machines/${selectedMachine}/chart-data?model=${selectedModel}&hours=${timeRange}`)
      const mockData = generateMockChartData(timeRange);
      setChartData(mockData);
    } catch (error) {
      console.error('Failed to load chart data:', error);
    } finally {
      setLoading(false);
    }
  };

  const generateMockChartData = (hours) => {
    const now = new Date();
    const data = [];
    const timestamps = [];

    for (let i = hours; i >= 0; i--) {
      const timestamp = new Date(now.getTime() - i * 60 * 60 * 1000);
      timestamps.push(timestamp);

      // Generate realistic prediction curves
      const baseValue = 0.4 + Math.sin(i / 5) * 0.2;
      const prediction = baseValue + (Math.random() - 0.5) * 0.1;
      const uncertainty = 0.08 + Math.random() * 0.04;

      data.push({
        timestamp,
        prediction: Math.max(0, Math.min(1, prediction)),
        upper_band: Math.min(1, prediction + 2 * uncertainty),
        lower_band: Math.max(0, prediction - 2 * uncertainty),
        actual_scrap: Math.random() > 0.85 ? (Math.random() > 0.5 ? 1 : 0) : null,
      });
    }

    return data;
  };

  if (!chartData || loading) {
    return (
      <Center p={8}>
        <Spinner />
      </Center>
    );
  }

  // Prepare Plotly data
  const predictions = chartData.map((d) => d.prediction);
  const upper_bands = chartData.map((d) => d.upper_band);
  const lower_bands = chartData.map((d) => d.lower_band);
  const timestamps = chartData.map((d) =>
    d.timestamp.toLocaleString('en-US', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  );

  // Separate actual scrap events
  const scrapIndices = chartData
    .map((d, i) => (d.actual_scrap === 1 ? i : -1))
    .filter((i) => i >= 0);
  const goodIndices = chartData
    .map((d, i) => (d.actual_scrap === 0 ? i : -1))
    .filter((i) => i >= 0);

  const plotlyData = [
    // Lower confidence band (fill)
    {
      x: timestamps,
      y: lower_bands,
      fill: 'tonexty',
      fillcolor: 'rgba(59, 130, 246, 0.1)',
      line: { color: 'rgba(59, 130, 246, 0)' },
      hoverinfo: 'skip',
      showlegend: false,
      name: '',
    },
    // Upper confidence band
    {
      x: timestamps,
      y: upper_bands,
      fill: null,
      line: { color: 'rgba(59, 130, 246, 0.2)', dash: 'dash' },
      hovertemplate: '<b>Upper Confidence Band</b><br>%{y:.3f}<extra></extra>',
      name: 'Confidence Band (2σ)',
      showlegend: showConfidenceBands,
    },
    // Main prediction line
    {
      x: timestamps,
      y: predictions,
      mode: 'lines',
      line: { color: 'rgb(59, 130, 246)', width: 3 },
      hovertemplate: '<b>Prediction</b><br>%{y:.3f}<extra></extra>',
      name: 'Scrap Probability',
    },
    // Lower band line
    {
      x: timestamps,
      y: lower_bands,
      fill: null,
      line: { color: 'rgba(59, 130, 246, 0.2)', dash: 'dash' },
      hovertemplate: '<b>Lower Confidence Band</b><br>%{y:.3f}<extra></extra>',
      name: 'Confidence Band (2σ)',
      showlegend: false,
    },
  ];

  // Add actual scrap events if visible
  if (showActualEvents && scrapIndices.length > 0) {
    plotlyData.push({
      x: scrapIndices.map((i) => timestamps[i]),
      y: scrapIndices.map((i) => predictions[i]),
      mode: 'markers',
      marker: {
        color: 'rgb(239, 68, 68)',
        size: 10,
        symbol: 'diamond',
      },
      name: 'Actual Scrap Events',
      hovertemplate:
        '<b>Scrap Event</b><br>Prediction: %{y:.3f}<br>Timestamp: %{x}<extra></extra>',
    });
  }

  if (showActualEvents && goodIndices.length > 0) {
    plotlyData.push({
      x: goodIndices.map((i) => timestamps[i]),
      y: goodIndices.map((i) => predictions[i]),
      mode: 'markers',
      marker: {
        color: 'rgb(34, 197, 94)',
        size: 8,
        symbol: 'circle',
      },
      name: 'Good Products',
      hovertemplate:
        '<b>Good Product</b><br>Prediction: %{y:.3f}<br>Timestamp: %{x}<extra></extra>',
    });
  }

  const layout = {
    title: `Scrap Prediction Confidence - ${selectedModel}`,
    xaxis: {
      title: 'Time',
      type: 'category',
    },
    yaxis: {
      title: 'Scrap Probability (0-1)',
      range: [0, 1],
    },
    hovermode: 'x unified',
    height: 500,
    margin: { l: 60, r: 30, t: 50, b: 60 },
  };

  return (
    <Card>
      <CardBody>
        <VStack align="stretch" spacing={4}>
          {/* Controls */}
          <Grid templateColumns="repeat(auto-fit, minmax(200px, 1fr))" gap={3}>
            {!machineId && (
              <FormControl>
                <FormLabel fontSize="sm">Machine</FormLabel>
                <Select
                  size="sm"
                  value={selectedMachine || ''}
                  onChange={(e) =>
                    setSelectedMachine(e.target.value || null)
                  }
                >
                  <option value="">All Machines</option>
                  {machines?.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </Select>
              </FormControl>
            )}

            <FormControl>
              <FormLabel fontSize="sm">Model</FormLabel>
              <Select
                size="sm"
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </FormControl>

            <FormControl>
              <FormLabel fontSize="sm">Time Range</FormLabel>
              <Select
                size="sm"
                value={timeRange}
                onChange={(e) => setTimeRange(parseInt(e.target.value))}
              >
                <option value={1}>Last 1 hour</option>
                <option value={6}>Last 6 hours</option>
                <option value={24}>Last 24 hours</option>
                <option value={168}>Last 7 days</option>
                <option value={720}>Last 30 days</option>
              </Select>
            </FormControl>
          </Grid>

          {/* Toggle Buttons */}
          <HStack spacing={2}>
            <Button
              size="sm"
              variant={showConfidenceBands ? 'solid' : 'outline'}
              colorScheme={showConfidenceBands ? 'blue' : 'gray'}
              onClick={() => setShowConfidenceBands(!showConfidenceBands)}
            >
              {showConfidenceBands ? '✓' : '○'} Confidence Bands
            </Button>
            <Button
              size="sm"
              variant={showActualEvents ? 'solid' : 'outline'}
              colorScheme={showActualEvents ? 'blue' : 'gray'}
              onClick={() => setShowActualEvents(!showActualEvents)}
            >
              {showActualEvents ? '✓' : '○'} Actual Events
            </Button>
          </HStack>

          {/* Chart */}
          {loading ? (
            <Center p={8}>
              <Spinner />
            </Center>
          ) : (
            <Box w="full" overflowX="auto">
              <Plot
                data={plotlyData}
                layout={layout}
                config={{ responsive: true, displayModeBar: true }}
                style={{ width: '100%' }}
              />
            </Box>
          )}

          {/* Legend/Explanation */}
          <Box bg="gray.50" p={3} borderRadius="md">
            <Text fontSize="xs" fontWeight="bold" mb={2}>
              📊 Chart Explanation
            </Text>
            <Grid templateColumns="repeat(2, 1fr)" gap={2} fontSize="xs">
              <Text>
                <span style={{ color: 'rgb(59, 130, 246)' }}>━━</span> Prediction
                = Model's scrap probability
              </Text>
              <Text>
                <span style={{ color: 'rgba(59, 130, 246, 0.3)' }}>┈┈</span>
                Confidence bands = ±2σ uncertainty
              </Text>
              <Text color="red.600">◆ Scrap events = Actual scrap detected</Text>
              <Text color="green.600">● Good products = Confirmed good parts</Text>
            </Grid>
          </Box>
        </VStack>
      </CardBody>
    </Card>
  );
}
