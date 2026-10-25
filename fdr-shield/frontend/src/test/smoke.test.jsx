import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { client } from '../api/client';
import RoleGuard from '../components/common/RoleGuard';
import TrustBadge from '../components/common/TrustBadge';
import SplitViewer from '../components/fdr/SplitViewer';
import Login from '../pages/auth/Login';
import FileDropzone from '../components/common/FileDropzone';
import RefundDecisionPanel from '../components/refund/RefundDecisionPanel';
import FdrUploadForm from '../components/fdr/FdrUploadForm';
import { useAuthStore } from '../store/authStore';

vi.mock('../api/client', () => ({ client: { post: vi.fn(), get: vi.fn() } }));

describe('FDR-Shield UI smoke tests', () => {
  it('guards a route for the configured role', () => {
    useAuthStore.getState().setUser({ role: 'aicte_official' });
    render(<MemoryRouter initialEntries={['/official']}><Routes><Route path="/official" element={<RoleGuard roles={['aicte_official']}><p>Official private</p></RoleGuard>}/></Routes></MemoryRouter>);
    expect(screen.getByText('Official private')).toBeInTheDocument();
  });

  it('shows a semantic trust badge', () => {
    render(<TrustBadge badge="mismatch"/>);
    expect(screen.getByText('Mismatch')).toHaveClass('badge-red');
  });

  it('accepts a supported upload and reports the selected file', () => {
    render(<FileDropzone required/>);
    fireEvent.change(screen.getByLabelText(/Choose a PDF or image scan/), { target: { files: [new File(['%PDF-1.4'], 'receipt.pdf', { type: 'application/pdf' })] } });
    expect(screen.getByText('receipt.pdf')).toBeInTheDocument();
  });

  it('requires review confirmation for every extracted field before FDR submission', async () => {
    client.post.mockResolvedValueOnce({data:{fields:{fdr_number:'FDR-123',bank_name:'SBI',branch:null,amount:'1000',issue_date:'2025-01-01',maturity_date:'2030-01-01',holder:'College'},confidence:{fdr_number:.9,bank_name:.9,branch:0,amount:.9,issue_date:.9,maturity_date:.9,holder:.9}}});
    const onSubmit=vi.fn();
    render(<FdrUploadForm onSubmit={onSubmit}/>);
    fireEvent.change(screen.getByLabelText(/FDR scan/),{target:{files:[new File(['%PDF-1.4'],'fdr.pdf',{type:'application/pdf'})]}});
    fireEvent.click(screen.getByRole('button',{name:'Extract and prefill fields'}));
    await screen.findByDisplayValue('FDR-123');
    const submit=screen.getByRole('button',{name:'Submit confirmed FDR'});
    expect(submit).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
    screen.getAllByRole('checkbox').forEach(box=>fireEvent.click(box));
    expect(submit).toBeEnabled();
    fireEvent.submit(submit.closest('form'));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0].get('confirmed_fields')).toContain('maturity_date');
    expect(JSON.parse(onSubmit.mock.calls[0][0].get('field_provenance')).branch).toBe('DECLARED');
  });

  it('requires a reason before making a refund decision', () => {
    const onDecide = vi.fn();
    render(<RefundDecisionPanel refund={{id:3}} onDecide={onDecide}/>);
    expect(screen.getByRole('button', {name:'Approve release'})).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Decision remarks'), {target:{value:'Documents reviewed'}});
    fireEvent.click(screen.getByRole('button', {name:'Approve release'}));
    expect(onDecide).toHaveBeenCalledWith(3,'approved','Documents reviewed');
  });

  it('renders declared, OCR and bank comparison and marks a mismatch', () => {
    render(<SplitViewer fdr={{fdr_number:'FDR-12',declared_data:{amount:100}}} report={{ocr:{amount:100},bank:{found:true,amount:90},discrepancies:[{field:'amount'}]}}/>);
    expect(screen.getByText(/Mock bank match; demo only/)).toBeInTheDocument();
    expect(screen.getByText(/do not independently certify that an FDR is genuine/i)).toBeInTheDocument();
    expect(screen.getByRole('row', { name: /Amount/ })).toHaveClass('bg-red-50');
  });

  it('logs in and routes an institution to its portal', async () => {
    client.post.mockResolvedValue({data:{mfa_required:false,user:{id:1,email:'school@example.test',role:'institution',institution_id:1}}});
    render(<MemoryRouter initialEntries={['/institution/login']}><Routes><Route path="/institution/login" element={<Login/>}/><Route path="/institution" element={<p>Institution portal ready</p>}/></Routes></MemoryRouter>);
    fireEvent.change(screen.getByLabelText('Email address'), {target:{value:'school@example.test'}});
    fireEvent.change(screen.getByLabelText('Password'), {target:{value:'DemoPass123!'}});
    fireEvent.click(screen.getByRole('button', {name:'Continue securely'}));
    await waitFor(() => expect(screen.getByText('Institution portal ready')).toBeInTheDocument());
  });
});
