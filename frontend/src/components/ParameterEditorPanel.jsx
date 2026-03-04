import React, { useState, useEffect } from 'react';
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
  NumberInput,
  NumberInputField,
  NumberInputStepper,
  NumberIncrementButton,
  NumberDecrementButton,
  VStack,
  HStack,
  Text,
  Box,
  useToast,
  Grid,
  GridItem,
  Divider,
} from '@chakra-ui/react';

/**
 * ParameterEditorPanel - Modal for editing a single parameter
 *
 * Props:
 * - isOpen: boolean
 * - onClose: function
 * - parameter: parameter object to edit (or null for new)
 * - onSave: callback after save
 */
export default function ParameterEditorPanel({ isOpen, onClose, parameter, onSave }) {
  const [formData, setFormData] = useState({
    parameter_name: '',
    machine_id: '',
    part_number: '',
    tolerance_plus: 0,
    tolerance_minus: 0,
    default_set_value: 0,
    reason: '', // For edit history
  });
  const [loading, setLoading] = useState(false);
  const [csvDefaults, setCsvDefaults] = useState(null);
  const toast = useToast();

  useEffect(() => {
    if (parameter) {
      setFormData({
        parameter_name: parameter.parameter_name || '',
        machine_id: parameter.machine_id || '',
        part_number: parameter.part_number || '',
        tolerance_plus: parameter.tolerance_plus || 0,
        tolerance_minus: parameter.tolerance_minus || 0,
        default_set_value: parameter.default_set_value || 0,
        reason: '',
      });
      setCsvDefaults({
        tolerance_plus: parameter.csv_original_plus,
        tolerance_minus: parameter.csv_original_minus,
      });
    } else {
      setFormData({
        parameter_name: '',
        machine_id: '',
        part_number: '',
        tolerance_plus: 0,
        tolerance_minus: 0,
        default_set_value: 0,
        reason: '',
      });
      setCsvDefaults(null);
    }
  }, [parameter, isOpen]);

  const handleSave = async () => {
    if (!formData.parameter_name) {
      toast({
        title: 'Validation Error',
        description: 'Parameter name is required',
        status: 'error',
        duration: 5000,
      });
      return;
    }

    setLoading(true);
    try {
      const response = await fetch('/api/admin/parameters', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      if (!response.ok) throw new Error('Failed to save parameter');

      toast({
        title: 'Success',
        description: 'Parameter saved successfully',
        status: 'success',
        duration: 3000,
      });

      if (onSave) onSave();
      onClose();
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

  const handleRevertToCSV = async () => {
    if (!parameter) return;

    if (!window.confirm('Are you sure you want to revert to CSV defaults?')) {
      return;
    }

    setLoading(true);
    try {
      const response = await fetch(`/api/admin/parameters/${parameter.id}/revert`, {
        method: 'POST',
      });

      if (!response.ok) throw new Error('Failed to revert parameter');

      toast({
        title: 'Success',
        description: 'Parameter reverted to CSV defaults',
        status: 'success',
        duration: 3000,
      });

      if (onSave) onSave();
      onClose();
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

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="lg">
      <ModalOverlay />
      <ModalContent>
        <ModalHeader>
          {parameter ? 'Edit Parameter' : 'Create New Parameter'}
        </ModalHeader>
        <ModalCloseButton />

        <ModalBody>
          <VStack align="stretch" spacing={4}>
            <FormControl>
              <FormLabel>Parameter Name *</FormLabel>
              <Input
                placeholder="e.g., Cushion, Injection_time"
                value={formData.parameter_name}
                onChange={(e) =>
                  setFormData({ ...formData, parameter_name: e.target.value })
                }
                isDisabled={!!parameter}
              />
            </FormControl>

            <FormControl>
              <FormLabel>Machine ID (optional)</FormLabel>
              <Input
                placeholder="e.g., M231-11, leave empty for global"
                value={formData.machine_id}
                onChange={(e) =>
                  setFormData({ ...formData, machine_id: e.target.value })
                }
              />
            </FormControl>

            <FormControl>
              <FormLabel>Part Number (optional)</FormLabel>
              <Input
                placeholder="e.g., ABC-123, leave empty for machine-wide"
                value={formData.part_number}
                onChange={(e) =>
                  setFormData({ ...formData, part_number: e.target.value })
                }
              />
            </FormControl>

            <Divider />

            <Box bg="gray.50" p={4} borderRadius="md">
              <Text fontWeight="bold" mb={3}>
                Tolerance Settings
              </Text>

              <Grid templateColumns="1fr 1fr" gap={4} mb={4}>
                <FormControl>
                  <FormLabel fontSize="sm">Tolerance + (Upper)</FormLabel>
                  <NumberInput
                    value={formData.tolerance_plus}
                    onChange={(val) =>
                      setFormData({ ...formData, tolerance_plus: parseFloat(val) })
                    }
                    precision={3}
                    step={0.01}
                  >
                    <NumberInputField />
                    <NumberInputStepper>
                      <NumberIncrementButton />
                      <NumberDecrementButton />
                    </NumberInputStepper>
                  </NumberInput>
                </FormControl>

                <FormControl>
                  <FormLabel fontSize="sm">Tolerance - (Lower)</FormLabel>
                  <NumberInput
                    value={formData.tolerance_minus}
                    onChange={(val) =>
                      setFormData({ ...formData, tolerance_minus: parseFloat(val) })
                    }
                    precision={3}
                    step={0.01}
                  >
                    <NumberInputField />
                    <NumberInputStepper>
                      <NumberIncrementButton />
                      <NumberDecrementButton />
                    </NumberInputStepper>
                  </NumberInput>
                </FormControl>
              </Grid>

              <FormControl>
                <FormLabel fontSize="sm">Default Set Value (Setpoint)</FormLabel>
                <NumberInput
                  value={formData.default_set_value}
                  onChange={(val) =>
                    setFormData({ ...formData, default_set_value: parseFloat(val) })
                  }
                  precision={2}
                  step={0.1}
                >
                  <NumberInputField />
                  <NumberInputStepper>
                    <NumberIncrementButton />
                    <NumberDecrementButton />
                  </NumberInputStepper>
                </NumberInput>
              </FormControl>
            </Box>

            {csvDefaults && (
              <Box bg="blue.50" p={4} borderRadius="md" borderLeft="4px" borderColor="blue.500">
                <Text fontWeight="bold" mb={2} fontSize="sm">
                  CSV Defaults
                </Text>
                <Grid templateColumns="1fr 1fr" gap={2} fontSize="sm">
                  <Text>
                    Tolerance +:
                    <Text fontWeight="bold">{csvDefaults.tolerance_plus}</Text>
                  </Text>
                  <Text>
                    Tolerance -:
                    <Text fontWeight="bold">{csvDefaults.tolerance_minus}</Text>
                  </Text>
                </Grid>
              </Box>
            )}

            <FormControl>
              <FormLabel>Reason for Change (optional)</FormLabel>
              <Input
                placeholder="e.g., Adjusted based on recent production data"
                value={formData.reason}
                onChange={(e) =>
                  setFormData({ ...formData, reason: e.target.value })
                }
              />
            </FormControl>
          </VStack>
        </ModalBody>

        <ModalFooter>
          <HStack spacing={3}>
            {parameter && csvDefaults && (
              <Button
                colorScheme="orange"
                variant="outline"
                onClick={handleRevertToCSV}
                isLoading={loading}
              >
                Revert to CSV
              </Button>
            )}
            <Button variant="ghost" onClick={onClose} isDisabled={loading}>
              Cancel
            </Button>
            <Button
              colorScheme="green"
              onClick={handleSave}
              isLoading={loading}
            >
              Save
            </Button>
          </HStack>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
