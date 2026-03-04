import React, { useState } from 'react';
import {
  Box,
  Tabs,
  TabList,
  TabPanels,
  Tab,
  TabPanel,
  VStack,
  HStack,
  Heading,
  Text,
  Grid,
  Select as ChakraSelect,
  FormControl,
  FormLabel,
} from '@chakra-ui/react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import ConfidenceZoneChart from '../components/ConfidenceZoneChart';
import ParameterTrendChart from '../components/ParameterTrendChart';
import ModelComparisonScatter from '../components/ModelComparisonScatter';
import FleetComparisonHeatmap from '../components/FleetComparisonHeatmap';
import ModelPerformanceDashboard from '../components/ModelPerformanceDashboard';

/**
 * AnalyticsView - Comprehensive analytics dashboard with multiple visualization tabs
 *
 * Tabs:
 * 1. Prediction Confidence - Scrap probability with confidence bands
 * 2. Parameter Analysis - Sensor values with safe limit overlays
 * 3. Model Comparison - 2D scatter of model predictions
 * 4. Fleet Overview - Heatmap of all machines vs key metrics
 * 5. Detailed Metrics - Sub-tabbed detailed performance analysis
 */
export default function AnalyticsView() {
  const { machines } = useTelemetryStore();
  const [selectedTab, setSelectedTab] = useState(0);
  const [selectedMachine, setSelectedMachine] = useState(null);
  const [selectedModel, setSelectedModel] = useState('lightgbm_v1');

  const models = [
    { id: 'lightgbm_v1', name: 'LightGBM Classifier (v1)' },
    { id: 'lstm_attention_dual', name: 'LSTM Attention (Dual)' },
  ];

  return (
    <Box p={6}>
      <VStack align="stretch" spacing={6}>
        {/* Header */}
        <Box>
          <Heading size="lg" mb={2}>
            Advanced Analytics & Insights
          </Heading>
          <Text color="gray.600">
            Comprehensive analysis of predictions, parameters, model performance, and fleet health
          </Text>
        </Box>

        {/* Global Filters */}
        <HStack spacing={4} bg="gray.50" p={4} borderRadius="md">
          <Box minW="250px">
            <FormControl>
              <FormLabel fontSize="sm" fontWeight="bold" mb={2}>
                Focus Machine (optional)
              </FormLabel>
              <ChakraSelect
                value={selectedMachine || ''}
                onChange={(e) => setSelectedMachine(e.target.value || null)}
              >
                <option value="">All Machines (Fleet-wide)</option>
                {machines?.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </ChakraSelect>
            </FormControl>
          </Box>

          <Box minW="250px">
            <FormControl>
              <FormLabel fontSize="sm" fontWeight="bold" mb={2}>
                Primary Model
              </FormLabel>
              <ChakraSelect
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </ChakraSelect>
            </FormControl>
          </Box>
        </HStack>

        {/* Tabbed Interface */}
        <Tabs index={selectedTab} onChange={setSelectedTab} variant="soft-rounded">
          <TabList bg="gray.100" p={1} borderRadius="md">
            <Tab>Prediction Confidence</Tab>
            <Tab>Parameter Analysis</Tab>
            <Tab>Model Comparison</Tab>
            <Tab>Fleet Overview</Tab>
            <Tab>Detailed Metrics</Tab>
          </TabList>

          <TabPanels>
            {/* Tab 1: Prediction Confidence */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                <Box bg="blue.50" p={4} borderRadius="md">
                  <Text fontSize="sm" color="blue.700">
                    💡 Monitor scrap probability predictions with confidence intervals and actual outcomes
                  </Text>
                </Box>
                <ConfidenceZoneChart
                  machineId={selectedMachine}
                  timeRangeHours={24}
                />
              </VStack>
            </TabPanel>

            {/* Tab 2: Parameter Analysis */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                <Box bg="green.50" p={4} borderRadius="md">
                  <Text fontSize="sm" color="green.700">
                    📊 Track sensor parameter values against safe bounds (current limits vs CSV defaults)
                  </Text>
                </Box>
                <ParameterTrendChart
                  machineId={selectedMachine}
                  timeRangeHours={24}
                />
              </VStack>
            </TabPanel>

            {/* Tab 3: Model Comparison */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                <Box bg="orange.50" p={4} borderRadius="md">
                  <Text fontSize="sm" color="orange.700">
                    🎯 Compare how two different models agree or disagree on scrap predictions
                  </Text>
                </Box>
                <ModelComparisonScatter machineId={selectedMachine} />
              </VStack>
            </TabPanel>

            {/* Tab 4: Fleet Overview */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                <Box bg="purple.50" p={4} borderRadius="md">
                  <Text fontSize="sm" color="purple.700">
                    🏭 Fleet-wide health dashboard showing all machines across key metrics
                  </Text>
                </Box>
                <FleetComparisonHeatmap />
              </VStack>
            </TabPanel>

            {/* Tab 5: Detailed Metrics */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                <Box>
                  <Heading size="md" mb={4}>
                    Detailed Performance Analysis
                  </Heading>
                  <Text color="gray.600" mb={4}>
                    In-depth metrics for model {selectedModel}
                    {selectedMachine && ` on machine ${selectedMachine}`}
                  </Text>
                </Box>

                {/* Nested tabs for detailed metrics */}
                <Tabs variant="enclosed">
                  <TabList mb="1em">
                    <Tab>Dashboard</Tab>
                    <Tab>Metrics Trends</Tab>
                    <Tab>Confusion Matrix</Tab>
                    <Tab>ROC Analysis</Tab>
                  </TabList>

                  <TabPanels>
                    {/* Sub-tab 1: Dashboard */}
                    <TabPanel>
                      <VStack align="stretch" spacing={4}>
                        <Text color="gray.600" fontSize="sm">
                          Real-time accuracy metrics and performance indicators
                        </Text>
                        <ModelPerformanceDashboard
                          modelId={selectedModel}
                          machineId={selectedMachine}
                        />
                      </VStack>
                    </TabPanel>

                    {/* Sub-tab 2: Metrics Trends */}
                    <TabPanel>
                      <VStack align="stretch" spacing={4}>
                        <Box bg="blue.50" p={4} borderRadius="md">
                          <Text fontSize="sm" color="blue.700">
                            📈 Historical accuracy metrics trends (Precision, Recall, F1)
                          </Text>
                        </Box>
                        <Box
                          bg="gray.50"
                          p={8}
                          borderRadius="md"
                          textAlign="center"
                          color="gray.400"
                        >
                          Metrics trend chart coming soon...
                        </Box>
                      </VStack>
                    </TabPanel>

                    {/* Sub-tab 3: Confusion Matrix */}
                    <TabPanel>
                      <VStack align="stretch" spacing={4}>
                        <Box bg="purple.50" p={4} borderRadius="md">
                          <Text fontSize="sm" color="purple.700">
                            📊 Confusion matrix heatmap (TP/TN/FP/FN breakdown)
                          </Text>
                        </Box>
                        <Box
                          bg="gray.50"
                          p={8}
                          borderRadius="md"
                          textAlign="center"
                          color="gray.400"
                        >
                          Confusion matrix chart coming soon...
                        </Box>
                      </VStack>
                    </TabPanel>

                    {/* Sub-tab 4: ROC Analysis */}
                    <TabPanel>
                      <VStack align="stretch" spacing={4}>
                        <Box bg="red.50" p={4} borderRadius="md">
                          <Text fontSize="sm" color="red.700">
                            📉 ROC curves showing trade-off between TPR and FPR
                          </Text>
                        </Box>
                        <Box
                          bg="gray.50"
                          p={8}
                          borderRadius="md"
                          textAlign="center"
                          color="gray.400"
                        >
                          ROC curve chart coming soon...
                        </Box>
                      </VStack>
                    </TabPanel>
                  </TabPanels>
                </Tabs>
              </VStack>
            </TabPanel>
          </TabPanels>
        </Tabs>

        {/* Info Card */}
        <Box bg="gray.50" p={4} borderRadius="md" borderLeft="4px" borderColor="blue.500">
          <VStack align="stretch" spacing={2}>
            <Text fontWeight="bold" fontSize="sm">
              💡 Analytics Tips
            </Text>
            <Text fontSize="xs" color="gray.600">
              • Use machine selector to focus on specific equipment or view fleet-wide trends
            </Text>
            <Text fontSize="xs" color="gray.600">
              • Model selector changes primary visualization model across all tabs
            </Text>
            <Text fontSize="xs" color="gray.600">
              • Hover over chart elements for detailed information
            </Text>
            <Text fontSize="xs" color="gray.600">
              • Look for patterns in confidence bands, parameter drift, and model disagreements
            </Text>
          </VStack>
        </Box>
      </VStack>
    </Box>
  );
}
