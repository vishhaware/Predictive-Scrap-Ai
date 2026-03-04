import React, { useState, useEffect } from 'react';
import {
  Box,
  Tabs,
  TabList,
  TabPanels,
  Tab,
  TabPanel,
  VStack,
  HStack,
  Text,
  Heading,
  Select as ChakraSelect,
  Button,
  useToast,
} from '@chakra-ui/react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import ModelPerformanceDashboard from '../components/ModelPerformanceDashboard';

/**
 * ModelAnalyticsView - Comprehensive model performance analysis interface
 *
 * Tabs:
 * 1. Dashboard - Overall model metrics
 * 2. Model Comparison - Compare multiple models side-by-side
 * 3. Metrics Trend - Performance over time
 * 4. Uncertainty - Confidence/uncertainty analysis
 */
export default function ModelAnalyticsView() {
  const { machines } = useTelemetryStore();
  const [selectedTab, setSelectedTab] = useState(0);
  const [selectedMachine, setSelectedMachine] = useState(null);
  const [selectedModel, setSelectedModel] = useState('lightgbm_v1');
  const [compareModels, setCompareModels] = useState('lightgbm_v1');
  const toast = useToast();

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
            Model Performance Analytics
          </Heading>
          <Text color="gray.600">
            Comprehensive analysis of prediction model performance across machines
          </Text>
        </Box>

        {/* Controls */}
        <HStack spacing={4} bg="gray.50" p={4} borderRadius="md">
          <Box minW="200px">
            <Text fontSize="sm" fontWeight="bold" mb={2}>
              Select Machine
            </Text>
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
          </Box>

          <Box minW="250px">
            <Text fontSize="sm" fontWeight="bold" mb={2}>
              Select Model
            </Text>
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
          </Box>
        </HStack>

        {/* Tabbed Interface */}
        <Tabs index={selectedTab} onChange={setSelectedTab} variant="soft-rounded">
          <TabList bg="gray.100" p={1} borderRadius="md">
            <Tab>Dashboard</Tab>
            <Tab>Model Comparison</Tab>
            <Tab>Metrics Trend</Tab>
            <Tab>Uncertainty Analysis</Tab>
          </TabList>

          <TabPanels>
            {/* Tab 1: Dashboard */}
            <TabPanel>
              <ModelPerformanceDashboard
                modelId={selectedModel}
                machineId={selectedMachine}
              />
            </TabPanel>

            {/* Tab 2: Model Comparison */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                <Box bg="blue.50" p={4} borderRadius="md">
                  <Text fontSize="sm" color="blue.700">
                    💡 Compare the performance of different models on the same dataset
                  </Text>
                </Box>

                <HStack spacing={4} mb={4}>
                  <Box minW="250px">
                    <Text fontSize="sm" fontWeight="bold" mb={2}>
                      Models to Compare (CSV)
                    </Text>
                    <ChakraSelect
                      value={compareModels}
                      onChange={(e) => setCompareModels(e.target.value)}
                    >
                      <option value="lightgbm_v1">LightGBM v1</option>
                      <option value="lstm_attention_dual">LSTM Attention Dual</option>
                      <option value="lightgbm_v1,lstm_attention_dual">Both Models</option>
                    </ChakraSelect>
                  </Box>

                  <Button colorScheme="blue" alignSelf="flex-end">
                    Compare
                  </Button>
                </HStack>

                <Box bg="gray.50" p={6} borderRadius="md" textAlign="center" color="gray.400">
                  Model comparison visualization coming soon...
                </Box>
              </VStack>
            </TabPanel>

            {/* Tab 3: Metrics Trend */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                <Box bg="green.50" p={4} borderRadius="md">
                  <Text fontSize="sm" color="green.700">
                    📈 Track how model performance evolves over time
                  </Text>
                </Box>

                <HStack spacing={4} mb={4}>
                  <Box minW="150px">
                    <Text fontSize="sm" fontWeight="bold" mb={2}>
                      Time Window
                    </Text>
                    <ChakraSelect>
                      <option>Last 24 Hours</option>
                      <option>Last 7 Days</option>
                      <option>Last 30 Days</option>
                    </ChakraSelect>
                  </Box>
                </HStack>

                <Box bg="gray.50" p={6} borderRadius="md" textAlign="center" color="gray.400">
                  Metrics trend chart coming soon...
                </Box>
              </VStack>
            </TabPanel>

            {/* Tab 4: Uncertainty Analysis */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                <Box bg="purple.50" p={4} borderRadius="md">
                  <Text fontSize="sm" color="purple.700">
                    🎯 Analyze prediction confidence and uncertainty bounds
                  </Text>
                </Box>

                <HStack spacing={4} mb={4}>
                  <Box minW="200px">
                    <Text fontSize="sm" fontWeight="bold" mb={2}>
                      Confidence Range
                    </Text>
                    <ChakraSelect>
                      <option>±1σ (68% confidence)</option>
                      <option>±2σ (95% confidence)</option>
                      <option>±3σ (99.7% confidence)</option>
                    </ChakraSelect>
                  </Box>
                </HStack>

                <Box bg="gray.50" p={6} borderRadius="md" textAlign="center" color="gray.400">
                  Uncertainty visualization coming soon...
                </Box>
              </VStack>
            </TabPanel>
          </TabPanels>
        </Tabs>
      </VStack>
    </Box>
  );
}
