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
  Stat,
  StatLabel,
  StatNumber,
  StatHelpText,
  StatArrow,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Badge,
  Button,
  useDisclosure,
  useToast,
  Tabs,
  TabList,
  TabPanels,
  Tab,
  TabPanel,
  Spinner,
  Center,
  Select as ChakraSelect,
  FormControl,
  FormLabel,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalFooter,
  ModalCloseButton,
} from '@chakra-ui/react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import ValidationRulesEditor from '../components/ValidationRulesEditor';
import DriftDetectionChart from '../components/DriftDetectionChart';
import { toFiniteOrNull, toFixedSafe } from '../utils/number';

/**
 * DataQualityView - Comprehensive data quality monitoring dashboard
 *
 * Features:
 * - Real-time violation summary (count, critical, warning)
 * - Recent violations table with sorting/filtering
 * - Validation rules editor with modal
 * - Concept drift detection per sensor
 * - Sensor completeness heatmap
 */
export default function DataQualityView() {
  const { machines } = useTelemetryStore();
  const {
    dataQualityViolations,
    validationRules,
    validationLoading,
    loadDataQualityViolations,
    loadValidationRules,
    createValidationRule,
    deleteValidationRule,
  } = useTelemetryStore();

  const [selectedTab, setSelectedTab] = useState(0);
  const [selectedMachine, setSelectedMachine] = useState(null);
  const [selectedSeverity, setSelectedSeverity] = useState(null);
  const [violationsSortBy, setViolationsSortBy] = useState('recent');
  const { isOpen, onOpen, onClose } = useDisclosure();
  const toast = useToast();

  useEffect(() => {
    loadDataQualityViolations(selectedMachine, 24, selectedSeverity);
    loadValidationRules();
  }, [selectedMachine, selectedSeverity]);

  const violations = dataQualityViolations || [];
  const rules = validationRules || [];

  // Summary statistics
  const totalViolations = violations.length;
  const criticalCount = violations.filter(v => v.severity === 'CRITICAL').length;
  const warningCount = violations.filter(v => v.severity === 'WARNING').length;

  // Calculate trend (would ideally come from backend)
  const violationTrend = criticalCount > 0 ? 'down' : 'up';

  const sortedViolations = [...violations].sort((a, b) => {
    if (violationsSortBy === 'severity') {
      const severityOrder = { CRITICAL: 0, WARNING: 1 };
      return (severityOrder[a.severity] || 2) - (severityOrder[b.severity] || 2);
    }
    return new Date(b.timestamp) - new Date(a.timestamp);
  });

  const getSeverityColor = (severity) => {
    if (severity === 'CRITICAL') return 'red';
    if (severity === 'WARNING') return 'yellow';
    return 'blue';
  };

  const getViolationTypeLabel = (type) => {
    const labels = {
      out_of_range: 'Out of Range',
      outlier: 'Outlier',
      missing: 'Missing Data',
      drift: 'Concept Drift',
    };
    return labels[type] || type;
  };

  const handleRuleDelete = async (ruleId) => {
    if (!window.confirm('Delete this validation rule?')) {
      return;
    }

    try {
      await deleteValidationRule(ruleId);
      toast({
        title: 'Success',
        description: 'Validation rule deleted',
        status: 'success',
        duration: 3000,
      });
    } catch (error) {
      toast({
        title: 'Error',
        description: error.message,
        status: 'error',
        duration: 5000,
      });
    }
  };

  return (
    <Box p={6}>
      <VStack align="stretch" spacing={6}>
        {/* Header */}
        <Box>
          <Heading size="lg" mb={2}>
            Data Quality & Validation
          </Heading>
          <Text color="gray.600">
            Monitor data quality violations, outliers, and concept drift across the fleet
          </Text>
        </Box>

        {/* Summary Cards */}
        <Grid templateColumns="repeat(3, 1fr)" gap={4}>
          <Card bg="gray.50">
            <CardBody>
              <Stat>
                <StatLabel>Total Violations (24h)</StatLabel>
                <StatNumber>{totalViolations}</StatNumber>
                <StatHelpText>
                  <StatArrow type={violationTrend} />
                  {criticalCount + warningCount} active
                </StatHelpText>
              </Stat>
            </CardBody>
          </Card>

          <Card bg="red.50">
            <CardBody>
              <Stat>
                <StatLabel>Critical Issues</StatLabel>
                <StatNumber color="red.600">{criticalCount}</StatNumber>
                <StatHelpText>
                  Require immediate attention
                </StatHelpText>
              </Stat>
            </CardBody>
          </Card>

          <Card bg="yellow.50">
            <CardBody>
              <Stat>
                <StatLabel>Warnings</StatLabel>
                <StatNumber color="orange.600">{warningCount}</StatNumber>
                <StatHelpText>
                  Monitor these values closely
                </StatHelpText>
              </Stat>
            </CardBody>
          </Card>
        </Grid>

        {/* Tabbed Interface */}
        <Tabs index={selectedTab} onChange={setSelectedTab} variant="soft-rounded">
          <TabList bg="gray.100" p={1} borderRadius="md">
            <Tab>Recent Violations</Tab>
            <Tab>Validation Rules</Tab>
            <Tab>Drift Detection</Tab>
            <Tab>Sensor Health</Tab>
          </TabList>

          <TabPanels>
            {/* Tab 1: Recent Violations */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                {/* Filters */}
                <HStack spacing={4}>
                  <Box minW="200px">
                    <FormControl>
                      <FormLabel fontSize="sm" mb={1}>
                        Filter by Machine
                      </FormLabel>
                      <ChakraSelect
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
                      </ChakraSelect>
                    </FormControl>
                  </Box>

                  <Box minW="150px">
                    <FormControl>
                      <FormLabel fontSize="sm" mb={1}>
                        Filter by Severity
                      </FormLabel>
                      <ChakraSelect
                        size="sm"
                        value={selectedSeverity || ''}
                        onChange={(e) =>
                          setSelectedSeverity(e.target.value || null)
                        }
                      >
                        <option value="">All Severities</option>
                        <option value="CRITICAL">Critical</option>
                        <option value="WARNING">Warning</option>
                      </ChakraSelect>
                    </FormControl>
                  </Box>

                  <Box minW="150px">
                    <FormControl>
                      <FormLabel fontSize="sm" mb={1}>
                        Sort By
                      </FormLabel>
                      <ChakraSelect
                        size="sm"
                        value={violationsSortBy}
                        onChange={(e) => setViolationsSortBy(e.target.value)}
                      >
                        <option value="recent">Most Recent</option>
                        <option value="severity">Severity</option>
                      </ChakraSelect>
                    </FormControl>
                  </Box>
                </HStack>

                {/* Violations Table */}
                {validationLoading ? (
                  <Center p={8}>
                    <Spinner />
                  </Center>
                ) : violations.length === 0 ? (
                  <Center p={8} color="gray.400">
                    <VStack>
                      <Text>No violations detected</Text>
                      <Text fontSize="sm">Your data looks clean!</Text>
                    </VStack>
                  </Center>
                ) : (
                  <Box overflowX="auto">
                    <Table variant="striped" colorScheme="gray" size="sm">
                      <Thead>
                        <Tr>
                          <Th>Machine</Th>
                          <Th>Sensor</Th>
                          <Th>Type</Th>
                          <Th>Severity</Th>
                          <Th>Value</Th>
                          <Th>Limits</Th>
                          <Th>Timestamp</Th>
                          <Th>Status</Th>
                        </Tr>
                      </Thead>
                      <Tbody>
                        {sortedViolations.map((v) => {
                          const details = typeof v.details === 'string' ? JSON.parse(v.details) : v.details;
                          const detailValue = toFiniteOrNull(details?.value);
                          const detailMin = toFiniteOrNull(details?.min);
                          const detailMax = toFiniteOrNull(details?.max);
                          return (
                            <Tr key={v.id}>
                              <Td fontWeight="bold">{v.machine_id}</Td>
                              <Td>{v.sensor_name}</Td>
                              <Td>
                                <Badge colorScheme="blue">
                                  {getViolationTypeLabel(v.type)}
                                </Badge>
                              </Td>
                              <Td>
                                <Badge colorScheme={getSeverityColor(v.severity)}>
                                  {v.severity}
                                </Badge>
                              </Td>
                              <Td isNumeric>
                                {toFixedSafe(detailValue, 3, 'N/A')}
                              </Td>
                              <Td>
                                {detailMin !== null && detailMax !== null ? (
                                  <Text fontSize="xs">
                                    [{toFixedSafe(detailMin, 2, 'N/A')}, {toFixedSafe(detailMax, 2, 'N/A')}]
                                  </Text>
                                ) : (
                                  'N/A'
                                )}
                              </Td>
                              <Td fontSize="xs">
                                {new Date(v.timestamp).toLocaleString()}
                              </Td>
                              <Td>
                                <Badge
                                  colorScheme={v.resolved_at ? 'gray' : 'orange'}
                                >
                                  {v.resolved_at ? 'Resolved' : 'Active'}
                                </Badge>
                              </Td>
                            </Tr>
                          );
                        })}
                      </Tbody>
                    </Table>
                  </Box>
                )}
              </VStack>
            </TabPanel>

            {/* Tab 2: Validation Rules */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                <HStack justify="space-between">
                  <Text color="gray.600" fontSize="sm">
                    Define and manage validation rules for your sensors
                  </Text>
                  <Button colorScheme="green" onClick={onOpen}>
                    + Add Rule
                  </Button>
                </HStack>

                {validationLoading ? (
                  <Center p={8}>
                    <Spinner />
                  </Center>
                ) : rules.length === 0 ? (
                  <Center p={8} color="gray.400">
                    <VStack>
                      <Text>No validation rules defined</Text>
                      <Button colorScheme="green" size="sm" onClick={onOpen}>
                        Create your first rule
                      </Button>
                    </VStack>
                  </Center>
                ) : (
                  <Box overflowX="auto">
                    <Table variant="striped" colorScheme="gray" size="sm">
                      <Thead>
                        <Tr>
                          <Th>Sensor</Th>
                          <Th>Machine</Th>
                          <Th>Rule Type</Th>
                          <Th>Configuration</Th>
                          <Th>Severity</Th>
                          <Th>Enabled</Th>
                          <Th>Actions</Th>
                        </Tr>
                      </Thead>
                      <Tbody>
                        {rules.map((rule) => (
                          <Tr key={rule.id}>
                            <Td fontWeight="bold">{rule.sensor_name}</Td>
                            <Td>{rule.machine_id || '(Global)'}</Td>
                            <Td>
                              <Badge colorScheme="purple">
                                {rule.rule_type}
                              </Badge>
                            </Td>
                            <Td fontSize="xs">
                              {rule.rule_type === 'RANGE'
                                ? `[${rule.min_value}, ${rule.max_value}]`
                                : rule.rule_type === 'OUTLIER'
                                  ? `Z-score > ${rule.zscore_threshold}`
                                  : rule.rule_type === 'DRIFT'
                                    ? `${rule.drift_method} > ${rule.drift_threshold}`
                                    : 'Completeness'}
                            </Td>
                            <Td>
                              <Badge colorScheme={getSeverityColor(rule.severity)}>
                                {rule.severity}
                              </Badge>
                            </Td>
                            <Td>
                              <Badge colorScheme={rule.enabled ? 'green' : 'gray'}>
                                {rule.enabled ? 'On' : 'Off'}
                              </Badge>
                            </Td>
                            <Td>
                              <Button
                                size="xs"
                                colorScheme="red"
                                variant="outline"
                                onClick={() => handleRuleDelete(rule.id)}
                              >
                                Delete
                              </Button>
                            </Td>
                          </Tr>
                        ))}
                      </Tbody>
                    </Table>
                  </Box>
                )}
              </VStack>
            </TabPanel>

            {/* Tab 3: Drift Detection */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                <Box bg="purple.50" p={4} borderRadius="md">
                  <Text fontSize="sm" color="purple.700">
                    📊 Monitor concept drift in sensor distributions over time
                  </Text>
                </Box>

                <DriftDetectionChart machineId={selectedMachine} />
              </VStack>
            </TabPanel>

            {/* Tab 4: Sensor Health */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                <Box bg="green.50" p={4} borderRadius="md">
                  <Text fontSize="sm" color="green.700">
                    ✓ Sensor data completeness and staleness tracking
                  </Text>
                </Box>

                <Center p={8} color="gray.400">
                  Sensor health heatmap coming soon...
                </Center>
              </VStack>
            </TabPanel>
          </TabPanels>
        </Tabs>

        {/* Validation Rules Editor Modal */}
        <ValidationRulesEditor
          isOpen={isOpen}
          onClose={onClose}
          onSave={() => {
            loadValidationRules();
            onClose();
          }}
        />
      </VStack>
    </Box>
  );
}
