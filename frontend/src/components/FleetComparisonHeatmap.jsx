import React, { useState, useEffect } from 'react';
import Plot from 'react-plotly.js';
import {
  Box,
  VStack,
  HStack,
  Grid,
  Text,
  Spinner,
  Center,
  Card,
  CardBody,
} from '@chakra-ui/react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { toFixedSafe, toNumberOr } from '../utils/number';

/**
 * FleetComparisonHeatmap - Machine x Metrics heatmap
 *
 * Shows:
 * - Rows: All machines in the fleet
 * - Columns: Key metrics (Risk, F1 Score, Precision, Recall, OEE)
 * - Color gradient: Red (bad) to Green (good)
 * - Hover: Detailed metric values
 */
export default function FleetComparisonHeatmap() {
  const { machines } = useTelemetryStore();
  const [heatmapData, setHeatmapData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadHeatmapData();
  }, []);

  const loadHeatmapData = async () => {
    setLoading(true);
    try {
      // In production: const data = await fetch('/api/ai/metrics-dashboard?include_fleet=true')
      const mockData = generateMockHeatmapData();
      setHeatmapData(mockData);
    } catch (error) {
      console.error('Failed to load heatmap data:', error);
    } finally {
      setLoading(false);
    }
  };

  const generateMockHeatmapData = () => {
    const fleetMachines = [
      { id: 'M231-11', name: 'M231-11 (Injection Molder A)' },
      { id: 'M356-57', name: 'M356-57 (Injection Molder B)' },
      { id: 'M471-23', name: 'M471-23 (Compression Unit)' },
      { id: 'M607-30', name: 'M607-30 (Injection Molder C)' },
      { id: 'M612-33', name: 'M612-33 (Precision Molding)' },
    ];

    const metrics = [
      { key: 'current_risk', label: 'Current Scrap Risk' },
      { key: 'f1_score', label: 'F1 Score' },
      { key: 'precision', label: 'Precision' },
      { key: 'recall', label: 'Recall' },
      { key: 'oee', label: 'OEE' },
    ];

    const data = {
      machines: fleetMachines,
      metrics: metrics,
      values: fleetMachines.map(() =>
        metrics.map(() => Math.random() * 100)
      ),
      details: fleetMachines.map(() =>
        metrics.map(() => ({
          value: (Math.random() * 100).toFixed(1),
          trend: Math.random() > 0.5 ? 'up' : 'down',
          status: Math.random() > 0.5 ? 'normal' : 'warning',
        }))
      ),
    };

    return data;
  };

  if (!heatmapData || loading) {
    return (
      <Center p={8}>
        <Spinner />
      </Center>
    );
  }

  const { machines: fleetMachines, metrics, values } = heatmapData;

  // Create hover text
  const hoverText = fleetMachines.map((machine, i) =>
    metrics.map((metric, j) => {
      const value = toNumberOr(values?.[i]?.[j], 0);
      return `<b>${machine.name}</b><br><b>${metric.label}</b><br>Value: ${toFixedSafe(value, 1, '0.0')}%`;
    })
  );

  const plotlyData = [
    {
      z: values,
      x: metrics.map((m) => m.label),
      y: fleetMachines.map((m) => m.id),
      type: 'heatmap',
      colorscale: [
        [0, 'rgb(239, 68, 68)'], // Red (bad)
        [0.5, 'rgb(251, 191, 36)'], // Yellow (caution)
        [1, 'rgb(34, 197, 94)'], // Green (good)
      ],
      hovertext: hoverText,
      hovertemplate: '%{hovertext}<extra></extra>',
      colorbar: {
        title: 'Score %',
        thickness: 15,
        len: 0.7,
      },
    },
  ];

  const layout = {
    title: 'Fleet Performance Heatmap',
    xaxis: {
      side: 'bottom',
    },
    yaxis: {
      autorange: 'reversed',
    },
    height: 400,
    margin: { l: 100, r: 50, t: 50, b: 80 },
  };

  return (
    <Card>
      <CardBody>
        <VStack align="stretch" spacing={4}>
          {/* Heatmap */}
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

          {/* Detailed Table */}
          <Box overflowX="auto" fontSize="xs">
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{
                  backgroundColor: '#f3f4f6',
                  borderBottom: '1px solid #e5e7eb',
                }}>
                  <th style={{ padding: '8px', textAlign: 'left', fontWeight: 'bold' }}>
                    Machine
                  </th>
                  {heatmapData.metrics.map((metric, i) => (
                    <th
                      key={i}
                      style={{
                        padding: '8px',
                        textAlign: 'center',
                        fontWeight: 'bold',
                      }}
                    >
                      {metric.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {heatmapData.machines.map((machine, i) => (
                  <tr
                    key={i}
                    style={{ borderBottom: '1px solid #e5e7eb' }}
                  >
                    <td
                      style={{
                        padding: '8px',
                        fontWeight: 'bold',
                        backgroundColor: '#f9fafb',
                      }}
                    >
                      {machine.id}
                    </td>
                    {heatmapData.metrics.map((_, j) => {
                      const value = toNumberOr(heatmapData.values?.[i]?.[j], 0);
                      const bgColor =
                        value >= 80
                          ? '#dcfce7'
                          : value >= 60
                            ? '#fef3c7'
                            : '#fee2e2';

                      return (
                        <td
                          key={j}
                          style={{
                            padding: '8px',
                            textAlign: 'center',
                            backgroundColor: bgColor,
                            fontWeight: '500',
                          }}
                        >
                          {toFixedSafe(value, 1, '0.0')}%
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </Box>

          {/* Legend */}
          <Box bg="gray.50" p={3} borderRadius="md">
            <Text fontSize="xs" fontWeight="bold" mb={2}>
              📊 Color Legend
            </Text>
            <HStack spacing={6} fontSize="xs">
              <Box display="flex" alignItems="center" gap={2}>
                <Box
                  w="20px"
                  h="20px"
                  bg="rgb(239, 68, 68)"
                  borderRadius="md"
                />
                <Text>&lt; 60% (Critical)</Text>
              </Box>
              <Box display="flex" alignItems="center" gap={2}>
                <Box
                  w="20px"
                  h="20px"
                  bg="rgb(251, 191, 36)"
                  borderRadius="md"
                />
                <Text>60-80% (Warning)</Text>
              </Box>
              <Box display="flex" alignItems="center" gap={2}>
                <Box
                  w="20px"
                  h="20px"
                  bg="rgb(34, 197, 94)"
                  borderRadius="md"
                />
                <Text>&gt; 80% (Healthy)</Text>
              </Box>
            </HStack>
          </Box>
        </VStack>
      </CardBody>
    </Card>
  );
}
