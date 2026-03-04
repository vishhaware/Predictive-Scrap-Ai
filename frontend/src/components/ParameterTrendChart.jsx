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
  Grid,
  Text,
  Spinner,
  Center,
  Card,
  CardBody,
} from '@chakra-ui/react';
import { useTelemetryStore } from '../store/useTelemetryStore';

/**
 * ParameterTrendChart - Parameter sensor values with safe limit overlays
 *
 * Features:
 * - Sensor value trend line
 * - Dynamic safe bounds (gray zone)
 * - CSV default bounds (dashed lines)
 * - Violation markers (yellow circles)
 * - Rolling average trend
 * - Parameter selector
 */
export default function ParameterTrendChart({
  machineId = null,
  timeRangeHours = 24,
}) {
  const { machines, parameterConfigs } = useTelemetryStore();
  const [selectedMachine, setSelectedMachine] = useState(machineId);
  const [selectedParameter, setSelectedParameter] = useState('Cushion');
  const [timeRange, setTimeRange] = useState(timeRangeHours);
  const [chartData, setChartData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showBounds, setShowBounds] = useState(true);
  const [showTrendLine, setShowTrendLine] = useState(true);

  const commonParameters = [
    'Cushion',
    'Injection_time',
    'Intensity',
    'Back_pressure',
    'Mold_temperature',
    'Gate_temperature',
    'Plunger_position',
    'Weight',
    'Thickness',
  ];

  useEffect(() => {
    loadChartData();
  }, [selectedMachine, selectedParameter, timeRange]);

  const loadChartData = async () => {
    setLoading(true);
    try {
      // In production: const data = await fetch(`/api/machines/${selectedMachine}/parameter-trend?param=${selectedParameter}&hours=${timeRange}`)
      const mockData = generateMockParameterData(timeRange);
      setChartData(mockData);
    } catch (error) {
      console.error('Failed to load chart data:', error);
    } finally {
      setLoading(false);
    }
  };

  const generateMockParameterData = (hours) => {
    const now = new Date();
    const data = [];
    const timestamps = [];

    // Get parameter config for bounds
    const paramConfig = parameterConfigs?.find(
      (p) => p.parameter_name === selectedParameter
    );
    const dynamicMin = (paramConfig?.tolerance_minus || 0.5) * -1;
    const dynamicMax = paramConfig?.tolerance_plus || 4.5;
    const csvMin = dynamicMin - 0.2;
    const csvMax = dynamicMax + 0.2;
    const setpoint = paramConfig?.default_set_value || 3.5;

    // Rolling average for trend
    const windowSize = 6;
    let values = [];

    for (let i = hours; i >= 0; i--) {
      const timestamp = new Date(now.getTime() - i * 60 * 60 * 1000);
      timestamps.push(timestamp);

      // Generate realistic parameter value around setpoint
      const baseValue = setpoint + (Math.random() - 0.5) * 0.8;
      const value = Math.max(csvMin, Math.min(csvMax, baseValue));

      values.push(value);

      // Calculate rolling average
      const recentValues = values.slice(-windowSize);
      const trendValue =
        recentValues.reduce((a, b) => a + b, 0) / recentValues.length;

      // Detect violation
      const isViolation = value < dynamicMin || value > dynamicMax;

      data.push({
        timestamp,
        value,
        trend: trendValue,
        isViolation,
        csv_min: csvMin,
        csv_max: csvMax,
        dynamic_min: dynamicMin,
        dynamic_max: dynamicMax,
        setpoint,
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
  const values = chartData.map((d) => d.value);
  const trends = chartData.map((d) => d.trend);
  const timestamps = chartData.map((d) =>
    d.timestamp.toLocaleString('en-US', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  );

  const dynamicMin = chartData[0]?.dynamic_min || 0;
  const dynamicMax = chartData[0]?.dynamic_max || 5;
  const csvMin = chartData[0]?.csv_min || -0.2;
  const csvMax = chartData[0]?.csv_max || 5.2;
  const setpoint = chartData[0]?.setpoint || 3.5;

  // Violation markers
  const violationIndices = chartData
    .map((d, i) => (d.isViolation ? i : -1))
    .filter((i) => i >= 0);

  const plotlyData = [
    // CSV bounds (static safe zone) - background
    {
      x: timestamps,
      y: Array(timestamps.length).fill(csvMax),
      fill: 'tonexty',
      fillcolor: 'rgba(200, 200, 200, 0.1)',
      line: { color: 'rgba(200, 200, 200, 0)' },
      hoverinfo: 'skip',
      showlegend: false,
      name: '',
    },
    // CSV max line
    {
      x: timestamps,
      y: Array(timestamps.length).fill(csvMax),
      fill: null,
      line: { color: 'rgba(100, 100, 100, 0.3)', dash: 'dot' },
      hovertemplate: '<b>CSV Upper Bound</b><br>%{y:.2f}<extra></extra>',
      name: 'CSV Bounds',
      showlegend: showBounds,
    },
    // Dynamic bounds (current safe zone)
    {
      x: timestamps,
      y: Array(timestamps.length).fill(dynamicMax),
      fill: 'tonexty',
      fillcolor: 'rgba(34, 197, 94, 0.15)',
      line: { color: 'rgba(34, 197, 94, 0)' },
      hoverinfo: 'skip',
      showlegend: false,
      name: '',
    },
    // Dynamic max line
    {
      x: timestamps,
      y: Array(timestamps.length).fill(dynamicMax),
      fill: null,
      line: { color: 'rgb(34, 197, 94)', width: 2 },
      hovertemplate: '<b>Current Upper Limit</b><br>%{y:.2f}<extra></extra>',
      name: 'Current Limits',
      showlegend: showBounds,
    },
    // Dynamic min line
    {
      x: timestamps,
      y: Array(timestamps.length).fill(dynamicMin),
      fill: null,
      line: { color: 'rgb(34, 197, 94)', width: 2 },
      hovertemplate: '<b>Current Lower Limit</b><br>%{y:.2f}<extra></extra>',
      name: 'Current Limits',
      showlegend: false,
    },
    // CSV min line
    {
      x: timestamps,
      y: Array(timestamps.length).fill(csvMin),
      fill: 'tonexty',
      fillcolor: 'rgba(200, 200, 200, 0.1)',
      line: { color: 'rgba(100, 100, 100, 0.3)', dash: 'dot' },
      hovertemplate: '<b>CSV Lower Bound</b><br>%{y:.2f}<extra></extra>',
      name: 'CSV Bounds',
      showlegend: false,
    },
    // Setpoint line
    {
      x: timestamps,
      y: Array(timestamps.length).fill(setpoint),
      fill: null,
      line: { color: 'rgb(59, 130, 246)', width: 1, dash: 'dash' },
      hovertemplate: '<b>Target Setpoint</b><br>%{y:.2f}<extra></extra>',
      name: 'Setpoint',
    },
    // Trend line
    {
      x: timestamps,
      y: trends,
      mode: 'lines',
      line: { color: 'rgba(139, 92, 246, 0.8)', width: 2 },
      hovertemplate: '<b>6-Cycle Trend</b><br>%{y:.2f}<extra></extra>',
      name: '6-Cycle Average',
      showlegend: showTrendLine,
    },
    // Main value line
    {
      x: timestamps,
      y: values,
      mode: 'lines+markers',
      line: { color: 'rgb(59, 130, 246)', width: 2 },
      marker: { size: 4, color: 'rgb(59, 130, 246)' },
      hovertemplate: '<b>Parameter Value</b><br>%{y:.2f}<extra></extra>',
      name: selectedParameter,
    },
  ];

  // Add violation markers
  if (violationIndices.length > 0) {
    plotlyData.push({
      x: violationIndices.map((i) => timestamps[i]),
      y: violationIndices.map((i) => values[i]),
      mode: 'markers',
      marker: {
        color: 'rgb(234, 179, 8)',
        size: 10,
        symbol: 'circle',
        line: { color: 'rgb(192, 132, 0)', width: 2 },
      },
      name: 'Out-of-Bounds',
      hovertemplate:
        '<b>⚠️ Limit Violation</b><br>Value: %{y:.2f}<br>Timestamp: %{x}<extra></extra>',
    });
  }

  const layout = {
    title: `${selectedParameter} Trend - ${selectedMachine || 'Fleet'}`,
    xaxis: {
      title: 'Time',
      type: 'category',
    },
    yaxis: {
      title: `${selectedParameter} Value`,
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
              <FormLabel fontSize="sm">Parameter</FormLabel>
              <Select
                size="sm"
                value={selectedParameter}
                onChange={(e) => setSelectedParameter(e.target.value)}
              >
                {commonParameters.map((p) => (
                  <option key={p} value={p}>
                    {p}
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
              </Select>
            </FormControl>
          </Grid>

          {/* Toggle Buttons */}
          <HStack spacing={2}>
            <Button
              size="sm"
              variant={showBounds ? 'solid' : 'outline'}
              colorScheme={showBounds ? 'green' : 'gray'}
              onClick={() => setShowBounds(!showBounds)}
            >
              {showBounds ? '✓' : '○'} Safe Bounds
            </Button>
            <Button
              size="sm"
              variant={showTrendLine ? 'solid' : 'outline'}
              colorScheme={showTrendLine ? 'purple' : 'gray'}
              onClick={() => setShowTrendLine(!showTrendLine)}
            >
              {showTrendLine ? '✓' : '○'} Trend Line
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
                <span style={{ color: 'rgb(59, 130, 246)' }}>━━</span> Value =
                Current sensor reading
              </Text>
              <Text>
                <span style={{ color: 'rgba(139, 92, 246, 0.8)' }}>━━</span>{' '}
                Trend = 6-cycle rolling average
              </Text>
              <Text>
                <span style={{ color: 'rgb(34, 197, 94)' }}>━━</span> Current
                Limits = Safe zone
              </Text>
              <Text>
                <span style={{ color: 'rgba(100, 100, 100, 0.3)' }}>┈┈</span>
                CSV Bounds = Original defaults
              </Text>
              <Text color="yellow.600">⚠️ Circles = Out-of-bounds violations</Text>
              <Text color="blue.600">━ ━ Setpoint = Target value</Text>
            </Grid>
          </Box>
        </VStack>
      </CardBody>
    </Card>
  );
}
