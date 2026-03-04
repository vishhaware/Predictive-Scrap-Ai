import React, { useState } from 'react';
import {
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalFooter,
  ModalCloseButton,
  Button,
  FormControl,
  FormLabel,
  Input,
  Select,
  NumberInput,
  NumberInputField,
  NumberInputStepper,
  NumberIncrementButton,
  NumberDecrementButton,
  VStack,
  HStack,
  Box,
  Text,
  useToast,
  Divider,
  Grid,
  GridItem,
} from '@chakra-ui/react';
import { useTelemetryStore } from '../store/useTelemetryStore';

/**
 * ValidationRulesEditor - Modal for creating/editing validation rules
 *
 * Allows configuration of:
 * - RANGE rules (min/max bounds)
 * - OUTLIER rules (Z-score threshold)
 * - DRIFT rules (concept drift detection)
 * - COMPLETENESS rules (missing data detection)
 */
export default function ValidationRulesEditor({ isOpen, onClose, onSave }) {
  const { machines, createValidationRule } = useTelemetryStore();
  const [loading, setLoading] = useState(false);
  const [ruleType, setRuleType] = useState('RANGE');
  const [formData, setFormData] = useState({
    sensor_name: '',
    machine_id: '',
    rule_type: 'RANGE',
    min_value: 0,
    max_value: 100,
    zscore_threshold: 3.0,
    drift_method: 'KL_DIVERGENCE',
    drift_threshold: 0.5,
    severity: 'WARNING',
    enabled: true,
  });
  const toast = useToast();

  const commonSensors = [
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

  const handleTypeChange = (type) => {
    setRuleType(type);
    setFormData({ ...formData, rule_type: type });
  };

  const handleSave = async () => {
    if (!formData.sensor_name) {
      toast({
        title: 'Validation Error',
        description: 'Please select a sensor',
        status: 'error',
        duration: 5000,
      });
      return;
    }

    if (ruleType === 'RANGE' && formData.min_value >= formData.max_value) {
      toast({
        title: 'Validation Error',
        description: 'Min value must be less than max value',
        status: 'error',
        duration: 5000,
      });
      return;
    }

    setLoading(true);
    try {
      await createValidationRule(formData);
      toast({
        title: 'Success',
        description: 'Validation rule created',
        status: 'success',
        duration: 3000,
      });
      if (onSave) onSave();
      handleClose();
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

  const handleClose = () => {
    setFormData({
      sensor_name: '',
      machine_id: '',
      rule_type: 'RANGE',
      min_value: 0,
      max_value: 100,
      zscore_threshold: 3.0,
      drift_method: 'KL_DIVERGENCE',
      drift_threshold: 0.5,
      severity: 'WARNING',
      enabled: true,
    });
    setRuleType('RANGE');
    onClose();
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} size="xl">
      <ModalOverlay />
      <ModalContent>
        <ModalHeader>Create Validation Rule</ModalHeader>
        <ModalCloseButton />

        <ModalBody>
          <VStack align="stretch" spacing={4}>
            {/* Basic Info */}
            <Box>
              <Text fontWeight="bold" mb={3}>
                Sensor & Scope
              </Text>
              <Grid templateColumns="1fr 1fr" gap={4}>
                <FormControl isRequired>
                  <FormLabel fontSize="sm">Sensor Name</FormLabel>
                  <Select
                    value={formData.sensor_name}
                    onChange={(e) =>
                      setFormData({ ...formData, sensor_name: e.target.value })
                    }
                  >
                    <option value="">Select a sensor...</option>
                    {commonSensors.map((sensor) => (
                      <option key={sensor} value={sensor}>
                        {sensor}
                      </option>
                    ))}
                  </Select>
                </FormControl>

                <FormControl>
                  <FormLabel fontSize="sm">Machine (optional)</FormLabel>
                  <Select
                    value={formData.machine_id}
                    onChange={(e) =>
                      setFormData({ ...formData, machine_id: e.target.value })
                    }
                  >
                    <option value="">Global Rule</option>
                    {machines?.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
            </Box>

            <Divider />

            {/* Rule Type Selection */}
            <Box>
              <Text fontWeight="bold" mb={3}>
                Rule Type
              </Text>
              <HStack spacing={2}>
                {[
                  { value: 'RANGE', label: 'Range' },
                  { value: 'OUTLIER', label: 'Outlier' },
                  { value: 'DRIFT', label: 'Drift' },
                  { value: 'COMPLETENESS', label: 'Completeness' },
                ].map((type) => (
                  <Button
                    key={type.value}
                    variant={ruleType === type.value ? 'solid' : 'outline'}
                    colorScheme={ruleType === type.value ? 'blue' : 'gray'}
                    size="sm"
                    onClick={() => handleTypeChange(type.value)}
                  >
                    {type.label}
                  </Button>
                ))}
              </HStack>
            </Box>

            <Divider />

            {/* Rule-Specific Parameters */}
            <Box>
              <Text fontWeight="bold" mb={3}>
                Rule Configuration
              </Text>

              {ruleType === 'RANGE' && (
                <Grid templateColumns="1fr 1fr" gap={4}>
                  <FormControl>
                    <FormLabel fontSize="sm">Minimum Value</FormLabel>
                    <NumberInput
                      value={formData.min_value}
                      onChange={(val) =>
                        setFormData({ ...formData, min_value: parseFloat(val) })
                      }
                      step={0.1}
                    >
                      <NumberInputField />
                      <NumberInputStepper>
                        <NumberIncrementButton />
                        <NumberDecrementButton />
                      </NumberInputStepper>
                    </NumberInput>
                  </FormControl>

                  <FormControl>
                    <FormLabel fontSize="sm">Maximum Value</FormLabel>
                    <NumberInput
                      value={formData.max_value}
                      onChange={(val) =>
                        setFormData({ ...formData, max_value: parseFloat(val) })
                      }
                      step={0.1}
                    >
                      <NumberInputField />
                      <NumberInputStepper>
                        <NumberIncrementButton />
                        <NumberDecrementButton />
                      </NumberInputStepper>
                    </NumberInput>
                  </FormControl>
                </Grid>
              )}

              {ruleType === 'OUTLIER' && (
                <FormControl>
                  <FormLabel fontSize="sm">Z-Score Threshold</FormLabel>
                  <NumberInput
                    value={formData.zscore_threshold}
                    onChange={(val) =>
                      setFormData({
                        ...formData,
                        zscore_threshold: parseFloat(val),
                      })
                    }
                    step={0.1}
                    min={1}
                    max={5}
                  >
                    <NumberInputField />
                    <NumberInputStepper>
                      <NumberIncrementButton />
                      <NumberDecrementButton />
                    </NumberInputStepper>
                  </NumberInput>
                  <Text fontSize="xs" color="gray.500" mt={1}>
                    Values beyond ±{formData.zscore_threshold}σ are considered outliers
                  </Text>
                </FormControl>
              )}

              {ruleType === 'DRIFT' && (
                <Grid templateColumns="1fr 1fr" gap={4}>
                  <FormControl>
                    <FormLabel fontSize="sm">Drift Method</FormLabel>
                    <Select
                      value={formData.drift_method}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          drift_method: e.target.value,
                        })
                      }
                    >
                      <option value="KL_DIVERGENCE">KL Divergence</option>
                      <option value="PSI">Population Stability Index</option>
                    </Select>
                  </FormControl>

                  <FormControl>
                    <FormLabel fontSize="sm">Drift Threshold</FormLabel>
                    <NumberInput
                      value={formData.drift_threshold}
                      onChange={(val) =>
                        setFormData({
                          ...formData,
                          drift_threshold: parseFloat(val),
                        })
                      }
                      step={0.05}
                      min={0.1}
                      max={2}
                    >
                      <NumberInputField />
                      <NumberInputStepper>
                        <NumberIncrementButton />
                        <NumberDecrementButton />
                      </NumberInputStepper>
                    </NumberInput>
                  </FormControl>
                </Grid>
              )}

              {ruleType === 'COMPLETENESS' && (
                <Box bg="blue.50" p={3} borderRadius="md">
                  <Text fontSize="sm" color="blue.700">
                    ✓ This rule triggers when required sensor data is missing from a
                    cycle
                  </Text>
                </Box>
              )}
            </Box>

            <Divider />

            {/* Severity & Status */}
            <Grid templateColumns="1fr 1fr" gap={4}>
              <FormControl>
                <FormLabel fontSize="sm">Severity Level</FormLabel>
                <Select
                  value={formData.severity}
                  onChange={(e) =>
                    setFormData({ ...formData, severity: e.target.value })
                  }
                >
                  <option value="WARNING">Warning</option>
                  <option value="CRITICAL">Critical</option>
                </Select>
              </FormControl>

              <FormControl>
                <FormLabel fontSize="sm">Status</FormLabel>
                <Select
                  value={formData.enabled ? 'enabled' : 'disabled'}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      enabled: e.target.value === 'enabled',
                    })
                  }
                >
                  <option value="enabled">Enabled</option>
                  <option value="disabled">Disabled</option>
                </Select>
              </FormControl>
            </Grid>

            {/* Preview */}
            <Box bg="gray.50" p={3} borderRadius="md">
              <Text fontSize="xs" fontWeight="bold" mb={1}>
                Rule Preview
              </Text>
              <Text fontSize="xs" color="gray.600">
                {formData.sensor_name || '(Sensor)'} on{' '}
                {formData.machine_id || 'all machines'}
                {ruleType === 'RANGE' &&
                  `: Must be in range [${formData.min_value}, ${formData.max_value}]`}
                {ruleType === 'OUTLIER' &&
                  `: Z-score must be ≤ ±${formData.zscore_threshold}`}
                {ruleType === 'DRIFT' &&
                  `: ${formData.drift_method} must be ≤ ${formData.drift_threshold}`}
                {ruleType === 'COMPLETENESS' && `: Data must be present in every cycle`}
              </Text>
            </Box>
          </VStack>
        </ModalBody>

        <ModalFooter>
          <HStack spacing={3}>
            <Button variant="ghost" onClick={handleClose} isDisabled={loading}>
              Cancel
            </Button>
            <Button
              colorScheme="green"
              onClick={handleSave}
              isLoading={loading}
            >
              Create Rule
            </Button>
          </HStack>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
