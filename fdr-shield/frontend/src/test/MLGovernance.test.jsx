import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import MLGovernance from '../pages/admin/MLGovernance';
import { client } from '../api/client';

vi.mock('../api/client', () => ({ client: { get: vi.fn() } }));

const capabilities = [
  { id: 'document_analysis', status: 'unknown', message: 'Confirmed during processing.' },
  { id: 'discrepancy_detection', status: 'available', message: 'Existing validation rules.' },
  { id: 'anomaly_detection', status: 'unavailable', message: 'Not deployed.' },
  { id: 'scrutiny_assistance', status: 'available', message: 'Advisory priorities.' },
];

describe('ML Governance feature showcase', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    client.get.mockImplementation(url => {
      if (url === '/admin/intelligence/capabilities') return Promise.resolve({ data: { capabilities } });
      if (url === '/verification/discrepancies') return Promise.resolve({ data: { items: [{
        id: 7, fdr_id: 42, fdr_number: 'FDR-42', institution_name: 'Sample College', field: 'amount',
        declared_value: '100000', extracted_value: '90000', source: 'ocr', severity: 'high',
        resolved: false, detected_at: '2026-10-30T08:00:00Z',
      }], has_more: false } });
      throw new Error(`Unexpected endpoint ${url}`);
    });
  });

  it('shows available business capabilities, the honest anomaly state, and real findings with case links', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><MemoryRouter><MLGovernance/></MemoryRouter></QueryClientProvider>);

    expect(await screen.findByRole('heading', { name: 'ML Governance' })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Intelligent Document Analysis' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Discrepancy Detection' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Anomaly Detection' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Not yet available' })).toBeDisabled();
    expect(screen.getByRole('link', { name: /Review Discrepancies/ })).toHaveAttribute('href', '/bureau/discrepancies');
    expect(await screen.findByText('FDR-42')).toBeInTheDocument();
    expect(screen.getByText('Sample College')).toBeInTheDocument();
    expect(screen.getByText('Amount mismatch')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /View case/ })).toHaveAttribute('href', '/bureau/scrutiny/42');
    expect(screen.queryByText(/dataset upload|training jobs|model artifacts|Ollama/i)).not.toBeInTheDocument();
  });

  it('shows API errors rather than treating them as an empty findings state', async () => {
    client.get.mockRejectedValue(new Error('service unavailable'));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><MemoryRouter><MLGovernance/></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText('Recent findings could not be loaded')).toBeInTheDocument();
    expect(screen.queryByText('No findings to review')).not.toBeInTheDocument();
  });
});
