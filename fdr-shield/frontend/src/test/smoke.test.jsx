import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { client } from '../api/client';
import RoleGuard from '../components/common/RoleGuard';
import TrustBadge from '../components/common/TrustBadge';
import SplitViewer from '../components/fdr/SplitViewer';
import Login from '../pages/auth/Login';
import { InstitutionRegister, OfficialRegister } from '../pages/auth/AuthPages';
import FileDropzone from '../components/common/FileDropzone';
import RefundDecisionPanel from '../components/refund/RefundDecisionPanel';
import FdrUploadForm from '../components/fdr/FdrUploadForm';
import SuperAdminSetup from '../pages/auth/SuperAdminSetup';
import AppRoutes from '../routes/AppRoutes';
import Layout from '../components/layout/Layout';
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

  it('explains when OCR completes without recognizing any fields', async () => {
    client.post.mockResolvedValueOnce({data:{
      fields:{fdr_number:null,bank_name:null,branch:null,amount:null,issue_date:null,maturity_date:null,holder:null},
      confidence:{fdr_number:0,bank_name:0,branch:0,amount:0,issue_date:0,maturity_date:0,holder:0},
    }});
    render(<FdrUploadForm/>);
    fireEvent.change(screen.getByLabelText(/FDR scan/),{target:{files:[new File(['scan'],'scan.png',{type:'image/png'})]}});
    fireEvent.click(screen.getByRole('button',{name:'Extract and prefill fields'}));
    expect(await screen.findByRole('status')).toHaveTextContent('OCR returned no readable fields');
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
    render(<MemoryRouter initialEntries={['/login?portal=institution']}><Routes><Route path="/login" element={<Login/>}/><Route path="/institution" element={<p>Institution portal ready</p>}/></Routes></MemoryRouter>);
    fireEvent.change(screen.getByLabelText('Email address'), {target:{value:'school@example.test'}});
    fireEvent.change(screen.getByLabelText('Password'), {target:{value:'DemoPass123!'}});
    fireEvent.click(screen.getByRole('button', {name:'Continue securely'}));
    await waitFor(() => expect(screen.getByText('Institution portal ready')).toBeInTheDocument());
  });

  it('reports a backend connection error separately from invalid credentials', async () => {
    client.post.mockRejectedValueOnce(new Error('Network Error'));
    render(<MemoryRouter initialEntries={['/login?portal=institution']}><Routes><Route path="/login" element={<Login/>}/></Routes></MemoryRouter>);
    fireEvent.change(screen.getByLabelText('Email address'), {target:{value:'school@example.test'}});
    fireEvent.change(screen.getByLabelText('Password'), {target:{value:'DemoPass123!'}});
    fireEvent.click(screen.getByRole('button', {name:'Continue securely'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach the login service');
  });

  it('toggles password visibility accessibly and prevents repeated submission while pending', async () => {
    let finish;
    client.post.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    render(<MemoryRouter initialEntries={['/login?portal=admin']}><Routes><Route path="/login" element={<Login/>}/><Route path="/admin" element={<p>Super Admin ready</p>}/></Routes></MemoryRouter>);
    const password = screen.getByLabelText('Password');
    expect(password).toHaveAttribute('type','password');
    fireEvent.click(screen.getByRole('button',{name:'Show password'}));
    expect(password).toHaveAttribute('type','text');
    fireEvent.click(screen.getByRole('button',{name:'Hide password'}));
    expect(password).toHaveAttribute('type','password');
    fireEvent.change(screen.getByLabelText('Email address'),{target:{value:'root@example.test'}});
    fireEvent.change(password,{target:{value:'not-rendered-in-dom'}});
    fireEvent.click(screen.getByRole('button',{name:'Continue securely'}));
    expect(screen.getByRole('button',{name:'Signing in…'})).toBeDisabled();
    expect(client.post).toHaveBeenCalledTimes(1);
    finish({data:{mfa_required:false,user:{id:2,email:'root@example.test',role:'admin'}}});
    await screen.findByText('Super Admin ready');
  });

  it.each([
    ['Institution registration', InstitutionRegister],
    ['AICTE Official application', OfficialRegister],
  ])('lets users reveal and hide their password on %s', (title, RegistrationPage) => {
    render(<MemoryRouter><RegistrationPage/></MemoryRouter>);
    const password = screen.getByLabelText(/Password/);
    expect(password).toHaveAttribute('type', 'password');
    fireEvent.change(password, {target: {value: 'VisibleOnlyOnRequest123!'}});
    fireEvent.click(screen.getByRole('button', {name: 'Show password'}));
    expect(password).toHaveAttribute('type', 'text');
    expect(password).toHaveValue('VisibleOnlyOnRequest123!');
    fireEvent.click(screen.getByRole('button', {name: 'Hide password'}));
    expect(password).toHaveAttribute('type', 'password');
  });

  it('blocks cross-role redirect targets after successful authentication', async () => {
    client.post.mockResolvedValueOnce({data:{mfa_required:false,user:{id:1,email:'college@example.test',role:'institution',institution_id:1}}});
    render(<MemoryRouter initialEntries={[{pathname:'/login',search:'?portal=institution',state:{from:{pathname:'/admin'}}}]}><Routes><Route path="/login" element={<Login/>}/><Route path="/institution" element={<p>Institution portal ready</p>}/><Route path="/admin" element={<p>Super Admin private</p>}/></Routes></MemoryRouter>);
    fireEvent.change(screen.getByLabelText('Email address'),{target:{value:'college@example.test'}});
    fireEvent.change(screen.getByLabelText('Password'),{target:{value:'Safe-Password-2026'}});
    fireEvent.click(screen.getByRole('button',{name:'Continue securely'}));
    await screen.findByText('Institution portal ready');
    expect(screen.queryByText('Super Admin private')).not.toBeInTheDocument();
  });

  it('submits the setup secret only with the initial Super Admin setup request', async () => {
    client.post.mockResolvedValueOnce({data:{message:'Initial Super Admin account created. You can now sign in.'}});
    render(<MemoryRouter><SuperAdminSetup/></MemoryRouter>);
    fireEvent.change(screen.getByLabelText('Full name'),{target:{value:'Initial Portal Owner'}});
    fireEvent.change(screen.getByLabelText('Official email'),{target:{value:'root@example.test'}});
    fireEvent.change(screen.getByLabelText('Phone number'),{target:{value:'+1 202 555 0164'}});
    fireEvent.change(screen.getByLabelText('Password'),{target:{value:'Complex-Initial-Passphrase-2026!'}});
    fireEvent.change(screen.getByLabelText('Confirm password'),{target:{value:'Complex-Initial-Passphrase-2026!'}});
    fireEvent.change(screen.getByLabelText('Super Admin setup secret'),{target:{value:'private-one-time-secret'}});
    fireEvent.click(screen.getByRole('button',{name:'Create initial Super Admin'}));
    await screen.findByText(/Initial Super Admin created/);
    expect(client.post).toHaveBeenCalledWith('/auth/register/super-admin',expect.objectContaining({
      setup_secret:'private-one-time-secret',email:'root@example.test',phone_number:'+1 202 555 0164',
    }));
  });

  it('offers three centralized portal choices and groups each allowed signup beside its role', () => {
    render(<MemoryRouter initialEntries={['/login']}><Routes><Route path="/login" element={<Login/>}/></Routes></MemoryRouter>);
    expect(screen.getByRole('heading',{name:'Choose your portal'})).toBeInTheDocument();
    expect(screen.getByRole('link',{name:'Register institution'})).toHaveAttribute('href','/institution/register');
    expect(screen.getByRole('link',{name:'Apply as AICTE Official'})).toHaveAttribute('href','/official/register');
    expect(screen.getByRole('link',{name:'First-time setup only'})).toHaveAttribute('href','/super-admin/setup');
  });

  it.each(['/institution/login','/official/login','/admin/login'])('%s routes to the one shared login screen', async path => {
    useAuthStore.getState().clearSession();
    render(<MemoryRouter initialEntries={[path]}><AppRoutes/></MemoryRouter>);
    expect(await screen.findByRole('heading',{name:'Sign in to FDR-Shield'})).toBeInTheDocument();
  });

  it.each(['/official/register','/super-admin/setup'])('%s renders outside dashboard chrome', path => {
    render(<MemoryRouter initialEntries={[path]}><Layout><p>Standalone public form</p></Layout></MemoryRouter>);
    expect(screen.getByText('Standalone public form')).toBeInTheDocument();
    expect(screen.queryByRole('navigation',{name:'Main navigation'})).not.toBeInTheDocument();
  });

  it('redirects direct protected-dashboard access to the shared role-choice login', async () => {
    useAuthStore.getState().clearSession();
    render(<MemoryRouter initialEntries={['/admin']}><Layout><AppRoutes/></Layout></MemoryRouter>);
    expect(await screen.findByRole('heading',{name:'Sign in to FDR-Shield'})).toBeInTheDocument();
    expect(screen.queryByRole('navigation',{name:'Main navigation'})).not.toBeInTheDocument();
  });

  it('routes a selected role from the three-choice login to the same shared login form', async () => {
    render(<MemoryRouter initialEntries={['/login']}><Routes><Route path="/login" element={<Login/>}/></Routes></MemoryRouter>);
    fireEvent.click(screen.getAllByRole('button',{name:'Continue to sign in'})[1]);
    expect(await screen.findByRole('heading',{name:'Sign in to FDR-Shield'})).toBeInTheDocument();
    expect(screen.getByText('AICTE Official')).toBeInTheDocument();
  });
});
