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
import { useAuthStore } from '../store/authStore';

vi.mock('../api/client', () => ({ client: { post: vi.fn(), get: vi.fn() } }));

describe('FDR-Shield UI smoke tests', () => {
  it('guards a route for the configured role', () => {
    useAuthStore.getState().setSession('jwt', { role: 'institution' });
    render(<MemoryRouter initialEntries={['/bureau']}><Routes><Route path="/bureau" element={<RoleGuard roles={['bureau_chief']}><p>Bureau private</p></RoleGuard>}/><Route path="/institution" element={<p>Institution home</p>}/></Routes></MemoryRouter>);
    expect(screen.getByText('Institution home')).toBeInTheDocument();
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
    expect(screen.getByText('Declared · OCR · Bank')).toBeInTheDocument();
    expect(screen.getByRole('row', { name: /Amount/ })).toHaveClass('bg-red-50');
  });

  it('logs in and routes an institution to its portal', async () => {
    client.post.mockResolvedValue({data:{access_token:'jwt',mfa_required:false}});
    client.get.mockResolvedValue({data:{id:1,email:'school@example.test',role:'institution',institution_id:1}});
    render(<MemoryRouter initialEntries={['/login']}><Routes><Route path="/login" element={<Login/>}/><Route path="/institution" element={<p>Institution portal ready</p>}/></Routes></MemoryRouter>);
    fireEvent.change(screen.getByLabelText('Email address'), {target:{value:'school@example.test'}});
    fireEvent.change(screen.getByLabelText('Password'), {target:{value:'DemoPass123!'}});
    fireEvent.click(screen.getByRole('button', {name:'Continue securely'}));
    await waitFor(() => expect(screen.getByText('Institution portal ready')).toBeInTheDocument());
  });
});
