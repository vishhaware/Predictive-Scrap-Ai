import React, { useState, useEffect } from 'react';
import Plot from 'react-plotly.js';
import {
  Box,
  VStack,
  HStack,
  FormControl,
  FormLabel,
  Select,
  Grid,
  Text,
  Spinner,
  Center,
  Card,
  CardBody,
  Badge,
} from '@chakra-ui/react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { toFixedSafe } from '../utils/number';

/**
 * ModelComparisonScatter - 2D scatter plot of two models' predictions
 *
 * Features:
 * - X-axis: Model A predictions
 * - Y-axis: Model B predictions
 * - Colors: Red=scrap, Green=good, Blue=uncertain
 * - Bubble size: Confidence score
 * - Diagonal reference line (perfect agreement)
 * - Quadrant analysis
 */
export default function ModelComparisonScatter({ machineId = null }) {
  const { machines } = useTelemetryStore();
  const [selectedMachine, setSelectedMachine] = useState(machineId);
  const [modelA, setModelA] = useState('lightgbm_v1');
  const [modelB, setModelB] = useState('lstm_attention_dual');
  const [chartData, setChartData] = useState(null);
  const [loading, setLoading] = useState(false);

  const models = [
    { id: 'lightgbm_v1', name: 'LightGBM Classifier (v1)' },
    { id: 'lstm_attention_dual', name: 'LSTM Attention (Dual)' },
  ];

  useEffect(() => {
    loadChartData();
  }, [selectedMachine, modelA, modelB]);

  const loadChartData = async () => {
    setLoading(true);
    try {
      // In production: const data = await fetch(`/api/ai/model-comparison?model_ids=${modelA},${modelB}&machine=${selectedMachine}`)
      const mockData = generateMockComparisonData();
      setChartData(mockData);
    } catch (error) {
      console.error('Failed to load comparison data:', error);
    } finally {
      setLoading(false);
    }
  };

  const generateMockComparisonData = () => {
    const data = [];
    for (let i = 0; i < 100; i++) {
      const actual = Math.random() > 0.8 ? 1 : 0;
      const modelAPred = 0.3 + Math.random() * 0.4 + (actual ? 0.2 : -0.15);
      const modelBPred = 0.3 + Math.random() * 0.4 + (actual ? 0.15 : -0.1);
      const confidence = 0.5 + Math.random() * 0.4;

      data.push({
        model_a_prediction: Math.max(0, Math.min(1, modelAPred)),
        model_b_prediction: Math.max(0, Math.min(1, modelBPred)),
        actual_scrap: actual,
        confidence,
        cycle_id: i,
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

  // Separate data by outcome
  const scrapData = chartData.filter((d) => d.actual_scrap === 1);
  const goodData = chartData.filter((d) => d.actual_scrap === 0);
  const uncertainData = chartData.filter(
    (d) => d.actual_scrap === null || d.actual_scrap === undefined
  );

  // Calculate quadrant statistics
  const calculateQuadrant = (d) => {
    const threshold = 0.5;
    const agreeScrap =
      d.model_a_prediction >= threshold && d.model_b_prediction >= threshold;
    const agreeGood =
      d.model_a_prediction < threshold && d.model_b_prediction < threshold;
    const disagree =
      (d.model_a_prediction >= threshold &&
        d.model_b_prediction < threshold) ||
      (d.model_a_prediction < threshold && d.model_b_prediction >= threshold);

    if (agreeScrap) return 'agree_scrap';
    if (agreeGood) return 'agree_good';
    if (disagree) return 'disagree';
    return 'other';
  };

  const quadrants = {
    agree_scrap: chartData.filter(
      (d) =>
        d.model_a_prediction >= 0.5 && d.model_b_prediction >= 0.5
    ).length,
    agree_good: chartData.filter(
      (d) =>
        d.model_a_prediction < 0.5 && d.model_b_prediction < 0.5
    ).length,
    disagree: chartData.filter(
      (d) =>
        (d.model_a_prediction >= 0.5 && d.model_b_prediction < 0.5) ||
        (d.model_a_prediction < 0.5 && d.model_b_prediction >= 0.5)
    ).length,
  };

  const totalData = scrapData.length + goodData.length + uncertainData.length;
  const agreementRate =
    toFixedSafe(((quadrants.agree_scrap + quadrants.agree_good) / Math.max(1, totalData)) * 100, 1, '0.0');

  const plotlyData = [
    // Scrap events (red)
    {
      x: scrapData.map((d) => d.model_a_prediction),
      y: scrapData.map((d) => d.model_b_prediction),
      mode: 'markers',
      marker: {
        size: scrapData.map((d) => d.confidence * 15 + 5),
        color: 'rgb(239, 68, 68)',
        opacity: 0.7,
        line: { color: 'rgb(127, 29, 29)', width: 1 },
      },
      text: scrapData.map(
        (d) =>
          `<b>Scrap Event</b><br>${modelA}: ${toFixedSafe(d.model_a_prediction, 3, 'N/A')}<br>${modelB}: ${toFixedSafe(d.model_b_prediction, 3, 'N/A')}<br>Confidence: ${toFixedSafe(d.confidence, 3, 'N/A')}`
      ),
      hovertemplate: '%{text}<extra></extra>',
      name: 'Scrap Events',
      customdata: scrapData.map((d) => d.cycle_id),
    },
    // Good products (green)
    {
      x: goodData.map((d) => d.model_a_prediction),
      y: goodData.map((d) => d.model_b_prediction),
      mode: 'markers',
      marker: {
        size: goodData.map((d) => d.confidence * 15 + 5),
        color: 'rgb(34, 197, 94)',
        opacity: 0.7,
        line: { color: 'rgb(20, 83, 45)', width: 1 },
      },
      text: goodData.map(
        (d) =>
          `<b>Good Product</b><br>${modelA}: ${toFixedSafe(d.model_a_prediction, 3, 'N/A')}<br>${modelB}: ${toFixedSafe(d.model_b_prediction, 3, 'N/A')}<br>Confidence: ${toFixedSafe(d.confidence, 3, 'N/A')}`
      ),
      hovertemplate: '%{text}<extra></extra>',
      name: 'Good Products',
    },
    // Perfect agreement line (y=x)
    {
      x: [0, 1],
      y: [0, 1],
      mode: 'lines',
      line: { color: 'rgba(100, 100, 100, 0.3)', width: 2, dash: 'dash' },
      hoverinfo: 'skip',
      name: 'Perfect Agreement',
    },
    // Threshold lines
    {
      x: [0.5, 0.5],
      y: [0, 1],
      mode: 'lines',
      line: { color: 'rgba(0, 0, 0, 0.1)', width: 1, dash: 'dot' },
      hoverinfo: 'skip',
      showlegend: false,
    },
    {
      x: [0, 1],
      y: [0.5, 0.5],
      mode: 'lines',
      line: { color: 'rgba(0, 0, 0, 0.1)', width: 1, dash: 'dot' },
      hoverinfo: 'skip',
      showlegend: false,
    },
  ];

  // Add uncertain data if exists
  if (uncertainData.length > 0) {
    plotlyData.push({
      x: uncertainData.map((d) => d.model_a_prediction),
      y: uncertainData.map((d) => d.model_b_prediction),
      mode: 'markers',
      marker: {
        size: uncertainData.map((d) => d.confidence * 15 + 5),
        color: 'rgb(59, 130, 246)',
        opacity: 0.5,
      },
      text: uncertainData.map(
        (d) =>
          `${modelA}: ${toFixedSafe(d.model_a_prediction, 3, 'N/A')}<br>${modelB}: ${toFixedSafe(d.model_b_prediction, 3, 'N/A')}`
      ),
      hovertemplate: '%{text}<extra></extra>',
      name: 'Untagged Data',
    });
  }

  const layout = {
    title: `Model Comparison: ${modelA} vs ${modelB}`,
    xaxis: {
      title: modelA,
      range: [0, 1],
    },
    yaxis: {
      title: modelB,
      range: [0, 1],
    },
    hovermode: 'closest',
    height: 500,
    margin: { l: 60, r: 30, t: 50, b: 60 },
    shapes: [
      {
        type: 'rect',
        x0: 0.5,
        x1: 1,
        y0: 0.5,
        y1: 1,
        fillcolor: 'rgba(239, 68, 68, 0.05)',
        line: { color: 'rgba(0, 0, 0, 0)' },
        layer: 'below',
      },
      {
        type: 'rect',
        x0: 0,
        x1: 0.5,
        y0: 0,
        y1: 0.5,
        fillcolor: 'rgba(34, 197, 94, 0.05)',
        line: { color: 'rgba(0, 0, 0, 0)' },
        layer: 'below',
      },
    ],
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
              <FormLabel fontSize="sm">Model A (X-axis)</FormLabel>
              <Select
                size="sm"
                value={modelA}
                onChange={(e) => setModelA(e.target.value)}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </FormControl>

            <FormControl>
              <FormLabel fontSize="sm">Model B (Y-axis)</FormLabel>
              <Select
                size="sm"
                value={modelB}
                onChange={(e) => setModelB(e.target.value)}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </FormControl>
          </Grid>

          {/* Agreement Rate */}
          <HStack spacing={4}>
            <Box>
              <Text fontSize="xs" color="gray.600">
                Model Agreement
              </Text>
              <Text fontSize="lg" fontWeight="bold" color="green.600">
                {agreementRate}%
              </Text>
            </Box>
            <Box>
              <Text fontSize="xs" color="gray.600">
                Agree (Scrap)
              </Text>
              <Badge colorScheme="red">{quadrants.agree_scrap}</Badge>
            </Box>
            <Box>
              <Text fontSize="xs" color="gray.600">
                Agree (Good)
              </Text>
              <Badge colorScheme="green">{quadrants.agree_good}</Badge>
            </Box>
            <Box>
              <Text fontSize="xs" color="gray.600">
                Disagree
              </Text>
              <Badge colorScheme="orange">{quadrants.disagree}</Badge>
            </Box>
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
                <span style={{ color: 'rgb(239, 68, 68)' }}>●</span> Red = Scrap
                events
              </Text>
              <Text>
                <span style={{ color: 'rgb(34, 197, 94)' }}>●</span> Green = Good
                products
              </Text>
              <Text>━ ━ Diagonal = Perfect model agreement</Text>
              <Text>
                Bubble size = Prediction confidence
              </Text>
              <Text>Top-right quadrant = Both predict scrap</Text>
              <Text>Bottom-left quadrant = Both predict good</Text>
            </Grid>
          </Box>
        </VStack>
      </CardBody>
    </Card>
  );
}
