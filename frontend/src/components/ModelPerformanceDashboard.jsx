import React, { useState, useEffect } from 'react';
import {
  Box,
  Grid,
  GridItem,
  Card,
  CardBody,
  CardHeader,
  Heading,
  Text,
  Stat,
  StatLabel,
  StatNumber,
  StatHelpText,
  StatArrow,
  Progress,
  VStack,
  HStack,
  Badge,
  Button,
  useToast,
  Spinner,
  Center,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
} from '@chakra-ui/react';
import { useTelemetryStore } from '../store/useTelemetryStore';

/**
 * ModelPerformanceDashboard - Display model accuracy metrics and statistics
 *
 * Shows:
 * - Precision, Recall, F1 Score, Accuracy cards with trends
 * - Confusion matrix summary
 * - Model comparison table
 * - Metric trends over time (sparklines)
 */
export default function ModelPerformanceDashboard({ modelId = 'lightgbm_v1', machineId = null }) {
  const { modelMetrics, metricsLoading, loadModelMetrics, triggerMetricsComputation } =
    useTelemetryStore();
  const [refreshing, setRefreshing] = useState(false);
  const toast = useToast();

  useEffect(() => {
    loadModelMetrics(modelId, machineId);
  }, [modelId, machineId]);

  const handleComputeMetrics = async () => {
    setRefreshing(true);
    try {
      const result = await triggerMetricsComputation(machineId);
      toast({
        title: 'Metrics Computed',
        description: `F1 Score: ${result.f1_score?.toFixed(3)}`,
        status: 'success',
        duration: 3000,
      });
      await loadModelMetrics(modelId, machineId);
    } catch (error) {
      toast({
        title: 'Error',
        description: error.message,
        status: 'error',
        duration: 5000,
      });
    } finally {
      setRefreshing(false);
    }
  };

  const getMetricColor = (value) => {
    if (value >= 0.85) return 'green';
    if (value >= 0.70) return 'yellow';
    return 'red';
  };

  const getMetricTrend = (value) => {
    if (value >= 0.8) return 'up';
    if (value <= 0.5) return 'down';
    return undefined;
  };

  if (metricsLoading && !modelMetrics.accuracy) {
    return (
      <Center p={8}>
        <Spinner />
      </Center>
    );
  }

  const metrics = modelMetrics || {};

  return (
    <Box p={6}>
      <VStack align="stretch" spacing={6}>
        {/* Header with refresh button */}
        <HStack justify="space-between">
          <VStack align="start">
            <Heading size="lg">Model Performance Metrics</Heading>
            <Text color="gray.600">
              {modelId}
              {machineId && ` • ${machineId}`}
            </Text>
          </VStack>
          <Button
            colorScheme="blue"
            onClick={handleComputeMetrics}
            isLoading={refreshing}
          >
            Compute Metrics
          </Button>
        </HStack>

        {/* Main metrics grid */}
        <Grid templateColumns="repeat(4, 1fr)" gap={4}>
          {/* Accuracy Card */}
          <Card bg="gray.50">
            <CardBody>
              <Stat>
                <StatLabel>Accuracy</StatLabel>
                <StatNumber>{(metrics.accuracy * 100 || 0).toFixed(1)}%</StatNumber>
                <StatHelpText>
                  <StatArrow type={getMetricTrend(metrics.accuracy)} />
                  Overall correct predictions
                </StatHelpText>
                <Progress
                  value={metrics.accuracy * 100 || 0}
                  size="sm"
                  mt={2}
                  colorScheme={getMetricColor(metrics.accuracy || 0)}
                />
              </Stat>
            </CardBody>
          </Card>

          {/* Precision Card */}
          <Card bg="gray.50">
            <CardBody>
              <Stat>
                <StatLabel>Precision</StatLabel>
                <StatNumber>{(metrics.precision * 100 || 0).toFixed(1)}%</StatNumber>
                <StatHelpText>
                  <StatArrow type={getMetricTrend(metrics.precision)} />
                  Positive predictions correct
                </StatHelpText>
                <Progress
                  value={metrics.precision * 100 || 0}
                  size="sm"
                  mt={2}
                  colorScheme={getMetricColor(metrics.precision || 0)}
                />
              </Stat>
            </CardBody>
          </Card>

          {/* Recall Card */}
          <Card bg="gray.50">
            <CardBody>
              <Stat>
                <StatLabel>Recall</StatLabel>
                <StatNumber>{(metrics.recall * 100 || 0).toFixed(1)}%</StatNumber>
                <StatHelpText>
                  <StatArrow type={getMetricTrend(metrics.recall)} />
                  Actual positives detected
                </StatHelpText>
                <Progress
                  value={metrics.recall * 100 || 0}
                  size="sm"
                  mt={2}
                  colorScheme={getMetricColor(metrics.recall || 0)}
                />
              </Stat>
            </CardBody>
          </Card>

          {/* F1 Score Card */}
          <Card bg="gray.50">
            <CardBody>
              <Stat>
                <StatLabel>F1 Score</StatLabel>
                <StatNumber>{(metrics.f1_score * 100 || 0).toFixed(1)}%</StatNumber>
                <StatHelpText>
                  <StatArrow type={getMetricTrend(metrics.f1_score)} />
                  Harmonic mean
                </StatHelpText>
                <Progress
                  value={metrics.f1_score * 100 || 0}
                  size="sm"
                  mt={2}
                  colorScheme={getMetricColor(metrics.f1_score || 0)}
                />
              </Stat>
            </CardBody>
          </Card>
        </Grid>

        {/* Additional metrics */}
        <Grid templateColumns="repeat(3, 1fr)" gap={4}>
          {/* ROC-AUC Card */}
          <Card>
            <CardHeader>
              <Heading size="md">ROC-AUC Score</Heading>
            </CardHeader>
            <CardBody>
              <VStack align="stretch" spacing={3}>
                <Text fontSize="2xl" fontWeight="bold">
                  {(metrics.roc_auc || 0).toFixed(3)}
                </Text>
                <Progress
                  value={metrics.roc_auc * 100 || 0}
                  colorScheme="purple"
                />
                <Text fontSize="sm" color="gray.600">
                  Area under ROC curve (discrimination ability)
                </Text>
              </VStack>
            </CardBody>
          </Card>

          {/* Brier Score Card */}
          <Card>
            <CardHeader>
              <Heading size="md">Brier Score</Heading>
            </CardHeader>
            <CardBody>
              <VStack align="stretch" spacing={3}>
                <Text fontSize="2xl" fontWeight="bold">
                  {(metrics.brier_score || 0).toFixed(4)}
                </Text>
                <Progress
                  value={Math.min((1 - (metrics.brier_score || 0)) * 100, 100)}
                  colorScheme="orange"
                />
                <Text fontSize="sm" color="gray.600">
                  Probability calibration (lower is better)
                </Text>
              </VStack>
            </CardBody>
          </Card>

          {/* Samples Card */}
          <Card>
            <CardHeader>
              <Heading size="md">Samples Evaluated</Heading>
            </CardHeader>
            <CardBody>
              <VStack align="stretch" spacing={3}>
                <Text fontSize="2xl" fontWeight="bold">
                  {metrics.samples_count || 0}
                </Text>
                <Badge colorScheme="blue" w="fit-content">
                  {metrics.samples_count ? 'Data Available' : 'No Data'}
                </Badge>
                <Text fontSize="sm" color="gray.600">
                  Cycles in evaluation window
                </Text>
              </VStack>
            </CardBody>
          </Card>
        </Grid>

        {/* Confusion Matrix */}
        {metrics.true_positives !== undefined && (
          <Card>
            <CardHeader>
              <Heading size="md">Confusion Matrix</Heading>
            </CardHeader>
            <CardBody>
              <Box overflowX="auto">
                <Table variant="simple" size="sm">
                  <Thead>
                    <Tr>
                      <Th>Predicted \ Actual</Th>
                      <Th isNumeric>No Defect</Th>
                      <Th isNumeric>Defect</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    <Tr>
                      <Td fontWeight="bold">No Defect (0)</Td>
                      <Td isNumeric bg="green.50" fontWeight="bold">
                        {metrics.true_negatives} (TN)
                      </Td>
                      <Td isNumeric bg="red.50" fontWeight="bold">
                        {metrics.false_positives} (FP)
                      </Td>
                    </Tr>
                    <Tr>
                      <Td fontWeight="bold">Defect (1)</Td>
                      <Td isNumeric bg="red.50" fontWeight="bold">
                        {metrics.false_negatives} (FN)
                      </Td>
                      <Td isNumeric bg="green.50" fontWeight="bold">
                        {metrics.true_positives} (TP)
                      </Td>
                    </Tr>
                  </Tbody>
                </Table>
              </Box>

              <Grid templateColumns="repeat(2, 1fr)" gap={4} mt={4}>
                <Box p={3} bg="gray.50" borderRadius="md">
                  <Text fontSize="sm" color="gray.600">
                    False Alarm Rate (FPR)
                  </Text>
                  <Text fontSize="lg" fontWeight="bold">
                    {metrics.true_negatives + metrics.false_positives > 0
                      ? (
                        (metrics.false_positives /
                          (metrics.true_negatives + metrics.false_positives)) *
                        100
                      ).toFixed(1)
                      : '0'}
                    %
                  </Text>
                </Box>

                <Box p={3} bg="gray.50" borderRadius="md">
                  <Text fontSize="sm" color="gray.600">
                    Missed Detection Rate (FNR)
                  </Text>
                  <Text fontSize="lg" fontWeight="bold">
                    {metrics.true_positives + metrics.false_negatives > 0
                      ? (
                        (metrics.false_negatives /
                          (metrics.true_positives + metrics.false_negatives)) *
                        100
                      ).toFixed(1)
                      : '0'}
                    %
                  </Text>
                </Box>
              </Grid>
            </CardBody>
          </Card>
        )}

        {/* Confidence Statistics */}
        {metrics.avg_confidence !== undefined && (
          <Card>
            <CardHeader>
              <Heading size="md">Prediction Confidence</Heading>
            </CardHeader>
            <CardBody>
              <Grid templateColumns="repeat(2, 1fr)" gap={4}>
                <Box>
                  <Text fontSize="sm" color="gray.600" mb={2}>
                    Average Confidence
                  </Text>
                  <Text fontSize="2xl" fontWeight="bold">
                    {(metrics.avg_confidence * 100 || 0).toFixed(1)}%
                  </Text>
                  <Progress
                    value={metrics.avg_confidence * 100 || 0}
                    mt={2}
                    colorScheme="cyan"
                  />
                </Box>

                <Box>
                  <Text fontSize="sm" color="gray.600" mb={2}>
                    Confidence Std Dev
                  </Text>
                  <Text fontSize="2xl" fontWeight="bold">
                    {(metrics.confidence_std || 0).toFixed(3)}
                  </Text>
                  <Text fontSize="xs" color="gray.500" mt={2}>
                    Consistency: {metrics.confidence_std < 0.1 ? 'High' : 'Moderate'}
                  </Text>
                </Box>
              </Grid>
            </CardBody>
          </Card>
        )}
      </VStack>
    </Box>
  );
}
