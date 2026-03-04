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
  FormControl,
  FormLabel,
  Input,
  Button,
  Text,
  GridItem,
  Grid,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Badge,
  useToast,
  Select as ChakraSelect,
  NumberInput,
  NumberInputField,
  NumberInputStepper,
  NumberIncrementButton,
  NumberDecrementButton,
  Spinner,
  Center,
} from '@chakra-ui/react';

/**
 * ParameterEditorView - Main container for parameter management
 *
 * Features:
 * - View all parameters with search/filter
 * - Edit parameter tolerances
 * - View parameter edit history
 * - Compare current vs CSV vs statistical bounds
 * - Revert to CSV defaults
 */
export default function ParameterEditorView() {
  const [selectedTab, setSelectedTab] = useState(0);
  const [parameters, setParameters] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const toast = useToast();

  useEffect(() => {
    loadParameters();
  }, []);

  const loadParameters = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/admin/parameters');
      if (!response.ok) throw new Error('Failed to load parameters');
      const data = await response.json();
      setParameters(data);
    } catch (error) {
      toast({
        title: 'Error',
        description: error.message,
        status: 'error',
        duration: 5000,
      });
    } finally {
      setLoading(false);
    }
  };

  const filteredParameters = parameters.filter(p =>
    p.parameter_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (p.machine_id && p.machine_id.toLowerCase().includes(searchTerm.toLowerCase()))
  );

  return (
    <Box p={6}>
      <VStack align="stretch" spacing={6}>
        <Box>
          <Text fontSize="2xl" fontWeight="bold" mb={2}>
            Parameter Editor
          </Text>
          <Text color="gray.600">
            Manage machine parameter tolerances and standard values
          </Text>
        </Box>

        <Tabs index={selectedTab} onChange={setSelectedTab} variant="enclosed">
          <TabList>
            <Tab>All Parameters</Tab>
            <Tab>By Machine</Tab>
            <Tab>Comparison</Tab>
            <Tab>Edit History</Tab>
          </TabList>

          <TabPanels>
            {/* Tab 1: All Parameters */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                <FormControl>
                  <FormLabel>Search Parameters</FormLabel>
                  <Input
                    placeholder="Search by name or machine..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                  />
                </FormControl>

                {loading ? (
                  <Center p={8}>
                    <Spinner />
                  </Center>
                ) : (
                  <Box overflowX="auto">
                    <Table variant="striped" colorScheme="gray">
                      <Thead>
                        <Tr>
                          <Th>Parameter Name</Th>
                          <Th>Machine</Th>
                          <Th>Tolerance +</Th>
                          <Th>Tolerance -</Th>
                          <Th>Setpoint</Th>
                          <Th>Source</Th>
                          <Th>Actions</Th>
                        </Tr>
                      </Thead>
                      <Tbody>
                        {filteredParameters.map((param) => (
                          <Tr key={param.id}>
                            <Td fontWeight="bold">{param.parameter_name}</Td>
                            <Td>{param.machine_id || '(Global)'}</Td>
                            <Td>{param.tolerance_plus.toFixed(3)}</Td>
                            <Td>{param.tolerance_minus.toFixed(3)}</Td>
                            <Td>{param.default_set_value.toFixed(2)}</Td>
                            <Td>
                              <Badge
                                colorScheme={
                                  param.source === 'USER'
                                    ? 'green'
                                    : param.source === 'CSV'
                                      ? 'blue'
                                      : 'gray'
                                }
                              >
                                {param.source}
                              </Badge>
                            </Td>
                            <Td>
                              <HStack spacing={2}>
                                <Button
                                  size="sm"
                                  colorScheme="blue"
                                  onClick={() => {
                                    // TODO: Open edit modal
                                  }}
                                >
                                  Edit
                                </Button>
                              </HStack>
                            </Td>
                          </Tr>
                        ))}
                      </Tbody>
                    </Table>
                  </Box>
                )}
              </VStack>
            </TabPanel>

            {/* Tab 2: By Machine */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                <Text color="gray.600">
                  View and manage parameters grouped by machine
                </Text>
                {/* TODO: Machine selector and grouped parameters */}
                <Center p={8} color="gray.400">
                  Machine view coming soon...
                </Center>
              </VStack>
            </TabPanel>

            {/* Tab 3: Comparison */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                <Text color="gray.600">
                  Compare current values vs CSV defaults vs statistical bounds
                </Text>
                {/* TODO: Comparison table */}
                <Center p={8} color="gray.400">
                  Comparison view coming soon...
                </Center>
              </VStack>
            </TabPanel>

            {/* Tab 4: Edit History */}
            <TabPanel>
              <VStack align="stretch" spacing={4}>
                <FormControl>
                  <FormLabel>Filter by Parameter</FormLabel>
                  <ChakraSelect placeholder="All parameters">
                    {Array.from(new Set(parameters.map(p => p.parameter_name))).map(name => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </ChakraSelect>
                </FormControl>

                {/* TODO: Load and display history from /api/admin/parameter-history */}
                <Center p={8} color="gray.400">
                  Edit history coming soon...
                </Center>
              </VStack>
            </TabPanel>
          </TabPanels>
        </Tabs>
      </VStack>
    </Box>
  );
}
